"""Where chunk vectors live: the owner's self-hosted Chroma. Tests swap in a stand-in.

Only vectors and chunk metadata are stored here. Chunk text stays in Postgres.
"""
import asyncio
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlparse

from app.core.config import get_settings

ADD_BATCH = 1000
TIMEOUT_SECONDS = 15
# The Chroma client is synchronous and has no timeout of its own. Its calls run on their own
# few threads, so a stalled server cannot use up the threads the rest of the app shares.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chroma")


class VectorStoreUnavailable(Exception):
    """Chroma could not be reached or refused the request."""


class VectorStore(Protocol):
    async def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None: ...

    async def query(
        self, vector: list[float], agent_id: uuid.UUID, k: int, filters: dict | None = None
    ) -> list[tuple[str, float]]:
        """Chunk IDs with their cosine similarity, best first, for one agent only."""

    async def delete_document(self, document_id: uuid.UUID) -> None: ...

    async def delete_agent(self, agent_id: uuid.UUID) -> None: ...


def _where(conditions: dict) -> dict:
    """Chroma wants one condition as-is and several wrapped in $and."""
    parts = [{key: value} for key, value in conditions.items()]
    return parts[0] if len(parts) == 1 else {"$and": parts}


class ChromaVectorStore:
    def __init__(self, url: str, embedding_model: str):
        self._url = url
        # One collection per embedding model: vectors from different models must never mix.
        self._name = "chunks_" + re.sub(r"[^a-zA-Z0-9_-]", "_", embedding_model)
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            import chromadb  # imported late: only needed when the knowledge base is used

            if not self._url:
                raise VectorStoreUnavailable("CHROMA_URL is not set")
            parsed = urlparse(self._url)
            client = chromadb.HttpClient(
                host=parsed.hostname, port=parsed.port or (443 if parsed.scheme == "https" else 8000),
                ssl=parsed.scheme == "https",
            )
            self._collection = client.get_or_create_collection(
                self._name, configuration={"hnsw": {"space": "cosine"}}
            )
        return self._collection

    async def _run(self, work):
        """The Chroma client is synchronous: run it off the event loop with a time limit, and
        turn any failure (including no answer in time) into one error type the callers report."""
        loop = asyncio.get_running_loop()
        try:
            call = loop.run_in_executor(_EXECUTOR, lambda: work(self._get_collection()))
            return await asyncio.wait_for(call, TIMEOUT_SECONDS)
        except VectorStoreUnavailable:
            raise
        except Exception as error:
            self._collection = None  # reconnect next time
            raise VectorStoreUnavailable(type(error).__name__) from error

    async def add(self, ids, vectors, metadatas):
        for start in range(0, len(ids), ADD_BATCH):
            batch = slice(start, start + ADD_BATCH)
            await self._run(
                lambda c, batch=batch: c.add(ids=ids[batch], embeddings=vectors[batch], metadatas=metadatas[batch])
            )

    async def query(self, vector, agent_id, k, filters=None):
        where = _where({"agent_id": str(agent_id), **(filters or {})})
        result = await self._run(
            lambda c: c.query(query_embeddings=[vector], n_results=k, where=where, include=["distances"])
        )
        # Chroma returns cosine distance; similarity is 1 minus it.
        return [(id_, 1.0 - distance) for id_, distance in zip(result["ids"][0], result["distances"][0])]

    async def delete_document(self, document_id):
        await self._run(lambda c: c.delete(where={"document_id": str(document_id)}))

    async def delete_agent(self, agent_id):
        await self._run(lambda c: c.delete(where={"agent_id": str(agent_id)}))


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    return ChromaVectorStore(settings.chroma_url, settings.embedding_model)
