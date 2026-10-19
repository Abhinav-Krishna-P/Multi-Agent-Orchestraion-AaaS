import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_agent
from app.api.schemas import DocumentOut
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.db.base import get_db
from app.db.models import Agent, Document
from app.rag.embeddings import Embedder, get_embedder
from app.rag.ingest import ingest_document
from app.rag.vector_store import VectorStore, VectorStoreUnavailable, get_vector_store

router = APIRouter()

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PASTE_CHARS = 1000
MAX_TITLE_CHARS = 100
MAX_DOCUMENTS = 50
FILE_TYPES = {".pdf": "pdf", ".txt": "txt"}


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_document", message)


def store_unavailable() -> ApiError:
    return ApiError(
        503, "vector_store_unavailable", "The knowledge base can't be reached right now. Try again in a moment."
    )


async def _read_upload(file: UploadFile) -> tuple[str, str, bytes]:
    name = (file.filename or "").strip()
    source_type = FILE_TYPES.get(name[-4:].lower())
    if source_type is None:
        raise _invalid("Upload a .pdf or .txt file.")
    data = await file.read(MAX_FILE_BYTES + 1)  # one byte over tells us it is too large
    if len(data) > MAX_FILE_BYTES:
        raise _invalid("That file is larger than 10 MB.")
    if not data:
        raise _invalid("That file is empty.")
    return name[:255], source_type, data


def _read_paste(title: str | None, text: str | None) -> tuple[str, str, bytes]:
    title, text = (title or "").strip(), (text or "").strip()
    if not title:
        raise _invalid("Give the text a title.")
    if len(title) > MAX_TITLE_CHARS:
        raise _invalid("Use 100 characters or fewer for the title.")
    if not text:
        raise _invalid("Write or paste some text first.")
    if len(text) > MAX_PASTE_CHARS:
        raise _invalid("Use 1,000 characters or fewer.")
    return title, "paste", text.encode()


def _duplicate() -> ApiError:
    return ApiError(409, "duplicate_document", "This document is already in the knowledge base.")


@router.post("/agents/{agent_id}/documents", response_model=DocumentOut, status_code=201)
async def add_document(
    background: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    title: str | None = Form(default=None),
    text: str | None = Form(default=None),
    agent: Agent = Depends(get_owned_agent),
    db: AsyncSession = Depends(get_db),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
):
    """Adds a file (.pdf or .txt) or a pasted text. It is processed in the background;
    the caller polls the list for its status."""
    if file is not None and (title is not None or text is not None):
        raise _invalid("Send a file or pasted text, not both.")
    if file is None and title is None and text is None:
        raise _invalid("Choose a file or paste some text.")
    name, source_type, data = await _read_upload(file) if file is not None else _read_paste(title, text)

    count = await db.scalar(select(func.count()).select_from(Document).where(Document.agent_id == agent.id))
    if count >= MAX_DOCUMENTS:
        raise ApiError(409, "document_limit", "This agent already has 50 documents. Delete one to add another.")
    content_hash = hashlib.sha256(data).hexdigest()
    exists = await db.scalar(
        select(Document.id).where(Document.agent_id == agent.id, Document.content_hash == content_hash)
    )
    if exists:
        raise _duplicate()

    document = Document(
        agent_id=agent.id, user_id=agent.user_id, filename=name, source_type=source_type,
        content_hash=content_hash, embedding_model=embedder.model,
        chunking_method=get_settings().chunking_method,
    )
    db.add(document)
    try:
        await db.commit()
    except IntegrityError as error:  # the same content arrived twice at once
        raise _duplicate() from error
    await db.refresh(document)
    background.add_task(ingest_document, document.id, data, embedder=embedder, store=store)
    return document


@router.get("/agents/{agent_id}/documents", response_model=list[DocumentOut])
async def list_documents(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Document).where(Document.agent_id == agent.id).order_by(Document.created_at.desc())
    )
    return rows.all()


@router.delete("/agents/{agent_id}/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    agent: Agent = Depends(get_owned_agent),
    db: AsyncSession = Depends(get_db),
    store: VectorStore = Depends(get_vector_store),
):
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.agent_id == agent.id))
    if document is None:
        raise not_found()
    # Vectors first: if Chroma is down nothing is deleted, so no vectors are left without an owner.
    try:
        await store.delete_document(document.id)
    except VectorStoreUnavailable as error:
        raise store_unavailable() from error
    await db.delete(document)
    await db.commit()
    return Response(status_code=204)
