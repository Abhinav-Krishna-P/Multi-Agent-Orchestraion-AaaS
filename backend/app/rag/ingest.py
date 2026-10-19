"""Processes one uploaded document in the background: extract, split, embed, store."""
import asyncio
import logging
import uuid

from sqlalchemy import update

from app.db.base import session_factory
from app.db.models import Document, DocumentChunk
from app.rag.chunking import split
from app.rag.embeddings import Embedder
from app.rag.extract import DocumentError, extract_pages
from app.rag.vector_store import VectorStore, VectorStoreUnavailable

logger = logging.getLogger(__name__)

INTERRUPTED = "Processing was interrupted. Delete this document and add it again."
STORE_DOWN = "The knowledge base can't be reached right now. Delete this document and try again."
UNEXPECTED = "This document couldn't be processed. Delete it and try again."


def chunk_metadata(document: Document, chunk_index: int, page: int | None) -> dict:
    """What is stored beside each vector, for filtering. Chroma does not accept null values."""
    metadata = {
        "agent_id": str(document.agent_id),
        "document_id": str(document.id),
        "document_name": document.filename,
        "source_type": document.source_type,
        "chunk_index": chunk_index,
    }
    if page is not None:
        metadata["page"] = page
    return metadata


async def _fail(document_id: uuid.UUID, reason: str) -> None:
    async with session_factory() as db:
        await db.execute(update(Document).where(Document.id == document_id).values(status="failed", error=reason))
        await db.commit()


async def _discard_vectors(store: VectorStore, document_id: uuid.UUID) -> None:
    try:
        await store.delete_document(document_id)
    except VectorStoreUnavailable:
        logger.warning("Vectors of a failed or deleted document could not be removed")


async def ingest_document(document_id: uuid.UUID, data: bytes, *, embedder: Embedder, store: VectorStore) -> None:
    async with session_factory() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return
        document.status = "processing"
        await db.commit()

    added_vectors = False
    try:
        pages = await asyncio.to_thread(extract_pages, document.source_type, data)
        chunks = split(pages, document.chunking_method, document.filename)
        vectors = await embedder.embed_documents([chunk.content for chunk in chunks])
        ids = [uuid.uuid4() for _ in chunks]
        metadatas = [chunk_metadata(document, index, chunk.page) for index, chunk in enumerate(chunks)]
        await store.add([str(id_) for id_ in ids], vectors, metadatas)
        added_vectors = True

        async with session_factory() as db:
            # The document may have been deleted while it was being processed.
            current = await db.get(Document, document_id)
            if current is None:
                await _discard_vectors(store, document_id)
                return
            db.add_all(
                DocumentChunk(
                    id=id_, document_id=document_id, agent_id=document.agent_id, chunk_index=index,
                    content=chunk.content, context=chunk.context, page=chunk.page,
                )
                for index, (id_, chunk) in enumerate(zip(ids, chunks))
            )
            current.status = "ready"
            current.error = None
            current.chunk_count = len(chunks)
            await db.commit()
    except DocumentError as error:
        await _fail(document_id, str(error))
    except VectorStoreUnavailable:
        await _fail(document_id, STORE_DOWN)
    except Exception as error:
        # Only the type is logged: the message could contain document text.
        logger.warning("A document could not be processed: %s", type(error).__name__)
        if added_vectors:
            await _discard_vectors(store, document_id)
        await _fail(document_id, UNEXPECTED)


async def sweep_interrupted_documents() -> None:
    """Run at startup: background work does not survive a restart, so anything still
    waiting or half-done will never finish."""
    async with session_factory() as db:
        await db.execute(
            update(Document)
            .where(Document.status.in_(("pending", "processing")))
            .values(status="failed", error=INTERRUPTED)
        )
        await db.commit()
