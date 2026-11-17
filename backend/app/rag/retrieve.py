"""Searching an agent's knowledge base: dense (cosine in Chroma), keyword (BM25), or both merged.

Every search is limited to one agent's ready documents, and can be narrowed further by
metadata (a document's name, a page). read_document() fetches by metadata alone, with no
similarity involved.
"""
import dataclasses
import re
import uuid
from dataclasses import dataclass

from langsmith import traceable
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.db.models import Document, DocumentChunk
from app.rag.embeddings import Embedder
from app.rag.vector_store import VectorStore

DENSE_K = 20
KEYWORD_K = 20
TOP_K = 5
READ_LIMIT = 8
# Below this best cosine similarity, a search counts as "nothing relevant". Tuned with the
# LangSmith tests (backend/evals).
MIN_SIMILARITY = 0.60
SEARCH_CACHE_SECONDS = 3600
EMBED_CACHE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_name: str
    page: int | None
    text: str  # what the model is given: the chunk, or its parent section
    similarity: float | None  # cosine similarity, when the dense search found it


class UnknownDocument(Exception):
    """A filter named a document the agent does not have."""

    def __init__(self, names: list[str]):
        super().__init__("unknown document")
        self.names = names


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def bm25_search(chunks: list[tuple[str, str]], query: str, k: int = KEYWORD_K) -> list[str]:
    """IDs of the chunks that best match the query's words, best first. Chunks sharing no
    word with the query are left out."""
    terms = tokenize(query)
    if not terms or not chunks:
        return []
    tokenized = [tokenize(text) for _, text in chunks]
    scores = BM25Okapi(tokenized).get_scores(terms)
    wanted = set(terms)
    # BM25 gives a zero or negative score to a word found in most chunks (and always in a
    # one-chunk set), so "shares a word" is checked directly instead of by score > 0.
    matches = [
        (score, id_) for score, (id_, _), tokens in zip(scores, chunks, tokenized) if wanted.intersection(tokens)
    ]
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [id_ for _, id_ in matches[:k]]


def rrf(*rankings: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion: merges ranked lists so items ranked high in several come first."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


async def document_names(db: AsyncSession, agent_id: uuid.UUID) -> list[str]:
    """Names of the agent's ready documents, sorted."""
    rows = await db.scalars(
        select(Document.filename).where(Document.agent_id == agent_id, Document.status == "ready").distinct()
    )
    return sorted(rows.all())


async def _fingerprint(db: AsyncSession, agent_id: uuid.UUID) -> str:
    """Names the agent's set of ready documents. A ready document never changes (documents can
    only be added or deleted), so this set decides everything a search can return: any change
    gives a new fingerprint, and cached results for the old set are simply never read again."""
    rows = await db.scalars(select(Document.id).where(Document.agent_id == agent_id, Document.status == "ready"))
    return cache.digest(sorted(str(id_) for id_ in rows.all()))


async def _resolve_name(db: AsyncSession, agent_id: uuid.UUID, document_name: str | None) -> str | None:
    """The stored spelling of a document name given in any letter case."""
    if document_name is None:
        return None
    names = await document_names(db, agent_id)
    for name in names:
        if name.lower() == document_name.strip().lower():
            return name
    raise UnknownDocument(names)


async def _chunks(
    db: AsyncSession, agent_id: uuid.UUID, document_name: str | None, page: int | None
) -> list[tuple[DocumentChunk, str]]:
    """The agent's chunks from ready documents, with their document's name, in reading order.

    shortcut: loads every matching chunk for each search (BM25 needs them all); fine for
    thousands of chunks per agent, move keyword search into an index beyond that.
    """
    query = (
        select(DocumentChunk, Document.filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.agent_id == agent_id, Document.status == "ready")
        .order_by(Document.created_at, Document.id, DocumentChunk.chunk_index)
    )
    if document_name is not None:
        query = query.where(func.lower(Document.filename) == document_name.lower())
    if page is not None:
        query = query.where(DocumentChunk.page == page)
    return [(chunk, name) for chunk, name in (await db.execute(query)).all()]


def _unique_hits(candidates: list[Hit], limit: int) -> list[Hit]:
    """Parent-child chunks can share one parent section: give the model each section once."""
    hits, seen = [], set()
    for hit in candidates:
        if hit.text not in seen:
            seen.add(hit.text)
            hits.append(hit)
        if len(hits) == limit:
            break
    return hits


@traceable(name="kb.embed_query", process_inputs=lambda inputs: {"query": inputs.get("query")})
async def _embed_query(embedder: Embedder, query: str) -> list[float]:
    # Keyed by the exact text: shared by all agents, since the vector only means anything to
    # someone who already has the text.
    key = f"embed:{embedder.model}:{cache.digest(query)}"
    if (vector := await cache.get_json(key)) is not None:
        return vector
    vector = await embedder.embed_query(query)
    await cache.set_json(key, vector, EMBED_CACHE_SECONDS)
    return vector


@traceable(name="kb.dense", process_inputs=lambda inputs: {"filters": inputs.get("filters")})
async def _dense(store: VectorStore, vector: list[float], agent_id: uuid.UUID, filters: dict) -> list[tuple[str, float]]:
    return await store.query(vector, agent_id, DENSE_K, filters or None)


@traceable(name="kb.keyword", process_inputs=lambda inputs: {"query": inputs.get("query")})
def _keyword(chunks: list[tuple[str, str]], query: str) -> list[str]:
    return bm25_search(chunks, query)


@traceable(name="kb.merge")
def _merge(dense_ids: list[str], keyword_ids: list[str]) -> list[str]:
    return rrf(dense_ids, keyword_ids)


_SEARCH_INPUTS = ("query", "mode", "document_name", "page", "min_similarity")


@traceable(name="kb.search", process_inputs=lambda inputs: {k: inputs.get(k) for k in _SEARCH_INPUTS})
async def search(
    agent_id: uuid.UUID,
    query: str,
    mode: str,
    *,
    db: AsyncSession,
    embedder: Embedder,
    store: VectorStore,
    min_similarity: float | None = None,
    document_name: str | None = None,
    page: int | None = None,
) -> list[Hit]:
    """Up to five chunks for the query. `mode` is "hybrid", "semantic" or "keyword"."""
    min_similarity = MIN_SIMILARITY if min_similarity is None else min_similarity
    name = await _resolve_name(db, agent_id, document_name)
    fingerprint = await _fingerprint(db, agent_id)
    key = f"kb:{agent_id}:{fingerprint}:{cache.digest(query, mode, name.lower() if name else None, page, min_similarity)}"
    if (cached := await cache.get_json(key)) is not None:
        return [Hit(**hit) for hit in cached]
    hits = await _search(agent_id, query, mode, db=db, embedder=embedder, store=store, min_similarity=min_similarity,
                         name=name, page=page)
    # Kept only if the documents didn't change while searching: otherwise the hits could belong to a
    # different set than the key names (and come back after that document is deleted).
    if await _fingerprint(db, agent_id) == fingerprint:
        await cache.set_json(key, [dataclasses.asdict(hit) for hit in hits], SEARCH_CACHE_SECONDS)
    return hits


async def _search(
    agent_id: uuid.UUID, query: str, mode: str, *, db: AsyncSession, embedder: Embedder, store: VectorStore,
    min_similarity: float, name: str | None, page: int | None,
) -> list[Hit]:
    rows = {str(chunk.id): (chunk, doc_name) for chunk, doc_name in await _chunks(db, agent_id, name, page)}
    if not rows:
        return []

    similarity: dict[str, float] = {}
    dense_ids: list[str] = []
    if mode != "keyword":
        filters = {key: value for key, value in (("document_name", name), ("page", page)) if value is not None}
        vector = await _embed_query(embedder, query)
        # Chroma may still hold a chunk whose document is no longer ready: keep known rows only.
        pairs = [(id_, sim) for id_, sim in await _dense(store, vector, agent_id, filters) if id_ in rows]
        if not pairs or pairs[0][1] < min_similarity:
            return []  # nothing close enough: better to say so than to hand over a poor match
        similarity = dict(pairs)
        dense_ids = [id_ for id_, _ in pairs]

    keyword_ids: list[str] = []
    if mode != "semantic":
        keyword_ids = _keyword([(id_, chunk.content) for id_, (chunk, _) in rows.items()], query)

    ranked = _merge(dense_ids, keyword_ids) if mode == "hybrid" else (dense_ids or keyword_ids)
    candidates = [
        Hit(id_, rows[id_][1], rows[id_][0].page, rows[id_][0].context or rows[id_][0].content, similarity.get(id_))
        for id_ in ranked
    ]
    return _unique_hits(candidates, TOP_K)


async def read_document(
    agent_id: uuid.UUID, document_name: str, page: int | None, *, db: AsyncSession, limit: int = READ_LIMIT
) -> list[Hit]:
    """A document's text by metadata alone, in reading order: no similarity involved."""
    name = await _resolve_name(db, agent_id, document_name)
    candidates = [
        Hit(str(chunk.id), doc_name, chunk.page, chunk.context or chunk.content, None)
        for chunk, doc_name in await _chunks(db, agent_id, name, page)
    ]
    return _unique_hits(candidates, limit)
