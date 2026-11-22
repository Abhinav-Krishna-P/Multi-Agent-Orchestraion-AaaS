import uuid

import pytest
from sqlalchemy import func, select

from tests.rag_fakes import FakeEmbedder, FakeVectorStore, make_pdf
from tests.test_agents import create_agent

TEXT = "Our store opens at nine in the morning and closes at six in the evening on weekdays."


@pytest.fixture
def rag(app):
    """Swaps Gemini embeddings and Chroma for in-memory stand-ins."""
    from types import SimpleNamespace

    from app.rag.embeddings import get_embedder
    from app.rag.vector_store import get_vector_store

    embedder, store = FakeEmbedder(), FakeVectorStore()
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    return SimpleNamespace(embedder=embedder, store=store)


async def paste(client, headers, agent_id, text=TEXT, title="Opening hours"):
    return await client.post(f"/agents/{agent_id}/documents", data={"title": title, "text": text}, headers=headers)


async def upload(client, headers, agent_id, name, data, content_type="application/octet-stream"):
    return await client.post(
        f"/agents/{agent_id}/documents", files={"file": (name, data, content_type)}, headers=headers
    )


async def listed(client, headers, agent_id):
    return (await client.get(f"/agents/{agent_id}/documents", headers=headers)).json()


async def chunk_rows(db, agent_id=None):
    from app.db.models import DocumentChunk

    query = select(DocumentChunk).order_by(DocumentChunk.chunk_index)
    if agent_id:
        query = query.where(DocumentChunk.agent_id == uuid.UUID(agent_id))
    return (await db.scalars(query)).all()


async def test_paste_text_becomes_ready(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    r = await paste(client, user_a, agent["id"])
    assert r.status_code == 201
    assert r.json()["status"] == "pending" and r.json()["source_type"] == "paste"
    assert r.json()["filename"] == "Opening hours"
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "ready" and doc["chunk_count"] == 1 and doc["error"] is None
    (chunk,) = await chunk_rows(db)
    assert chunk.content == f"[Opening hours]\n{TEXT}" and chunk.page is None
    (vector, metadata) = rag.store.items[str(chunk.id)]
    assert metadata == {
        "agent_id": agent["id"], "document_id": doc["id"], "document_name": "Opening hours",
        "source_type": "paste", "chunk_index": 0,
    }


async def test_txt_upload_becomes_ready(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    r = await upload(client, user_a, agent["id"], "notes.TXT", ("Line one.\n" * 300).encode())
    assert r.status_code == 201 and r.json()["source_type"] == "txt"
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "ready" and doc["chunk_count"] > 1
    assert len(rag.store.items) == doc["chunk_count"] == len(await chunk_rows(db))


async def test_txt_with_bom_is_read(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    await upload(client, user_a, agent["id"], "bom.txt", b"\xef\xbb\xbfHello there.")
    (chunk,) = await chunk_rows(db)
    assert chunk.content == "[bom.txt]\nHello there."


async def test_pdf_upload_keeps_pages(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    pdf = make_pdf(["Returns are accepted within thirty days.", "Shipping takes five days."])
    r = await upload(client, user_a, agent["id"], "policy.pdf", pdf)
    assert r.status_code == 201 and r.json()["source_type"] == "pdf"
    chunks = await chunk_rows(db)
    assert [c.page for c in chunks] == [1, 2]
    assert chunks[1].content == "[policy.pdf, page 2]\nShipping takes five days."
    assert rag.store.items[str(chunks[1].id)][1]["page"] == 2


async def test_pdf_with_some_empty_pages_is_indexed(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    await upload(client, user_a, agent["id"], "mixed.pdf", make_pdf(["", "Only this page has text.", ""]))
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "ready"
    assert [c.page for c in await chunk_rows(db)] == [2]


async def test_pdf_without_text_fails(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    await upload(client, user_a, agent["id"], "scan.pdf", make_pdf(["", ""]))
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed" and doc["error"] == "This PDF has no readable text."
    assert await chunk_rows(db) == [] and rag.store.items == {}


async def test_broken_pdf_fails_readably(client, user_a, rag):
    agent = await create_agent(client, user_a)
    await upload(client, user_a, agent["id"], "broken.pdf", b"this is not a pdf at all")
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed" and doc["error"] == "This PDF couldn't be opened."


async def test_binary_txt_fails(client, user_a, rag):
    agent = await create_agent(client, user_a)
    await upload(client, user_a, agent["id"], "data.txt", b"\xff\xfe\x00\x01binary\x00junk")
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed" and doc["error"] == "This file isn't readable text."


@pytest.mark.parametrize(
    "kind",
    ["wrong_extension", "too_large", "empty_file", "empty_paste", "long_paste", "long_title", "no_title", "nothing", "both"],
)
async def test_invalid_upload_422(client, user_a, rag, db, kind):
    from app.db.models import Document

    agent = await create_agent(client, user_a)
    url = f"/agents/{agent['id']}/documents"
    requests = {
        "wrong_extension": {"files": {"file": ("notes.md", b"# hi", "text/markdown")}},
        "too_large": {"files": {"file": ("big.txt", b"a" * (10 * 1024 * 1024 + 1), "text/plain")}},
        "empty_file": {"files": {"file": ("empty.txt", b"", "text/plain")}},
        "empty_paste": {"data": {"title": "T", "text": "   "}},
        "long_paste": {"data": {"title": "T", "text": "x" * 1001}},
        "long_title": {"data": {"title": "t" * 101, "text": "hello"}},
        "no_title": {"data": {"text": "hello"}},
        "nothing": {"data": {"unused": "1"}},
        "both": {"files": {"file": ("a.txt", b"hi", "text/plain")}, "data": {"title": "T", "text": "hello"}},
    }
    r = await client.post(url, headers=user_a, **requests[kind])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "invalid_document"
    assert await db.scalar(select(func.count()).select_from(Document)) == 0


async def test_paste_of_exactly_1000_chars_accepted(client, user_a, rag):
    agent = await create_agent(client, user_a)
    assert (await paste(client, user_a, agent["id"], text="y" * 1000)).status_code == 201


async def test_duplicate_refused_per_agent(client, user_a, rag):
    first = await create_agent(client, user_a, name="First")
    second = await create_agent(client, user_a, name="Second")
    assert (await paste(client, user_a, first["id"])).status_code == 201
    r = await paste(client, user_a, first["id"], title="Another title")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_document"
    assert r.json()["detail"]["message"] == "This document is already in the knowledge base."
    assert (await paste(client, user_a, second["id"])).status_code == 201


async def test_document_limit(client, user_a, rag, db):
    from app.db.models import Document

    agent = await create_agent(client, user_a)
    for i in range(50):
        db.add(Document(
            agent_id=uuid.UUID(agent["id"]), user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            filename=f"d{i}", source_type="paste", content_hash=f"h{i}", embedding_model="m", chunking_method="recursive",
        ))
    await db.commit()
    r = await paste(client, user_a, agent["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "document_limit"


async def test_embedding_busy_marks_failed(client, user_a, rag, db):
    from app.rag.extract import DocumentError

    rag.embedder.error = DocumentError("The embedding service is busy. Delete this document and try again later.")
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed"
    assert doc["error"] == "The embedding service is busy. Delete this document and try again later."


async def test_unexpected_error_marks_failed_without_detail(client, user_a, rag):
    rag.embedder.error = RuntimeError("secret internal detail")
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed"
    assert doc["error"] == "This document couldn't be processed. Delete it and try again."


async def test_store_down_marks_failed(client, user_a, rag, db):
    rag.store.fail = True
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    (doc,) = await listed(client, user_a, agent["id"])
    assert doc["status"] == "failed"
    assert doc["error"] == "The knowledge base can't be reached right now. Delete this document and try again."
    assert await chunk_rows(db) == []


async def test_delete_document_removes_chunks_and_vectors(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    await paste(client, user_a, agent["id"], text="A second, different note.", title="Other")
    keep, remove = await listed(client, user_a, agent["id"])  # newest first
    r = await client.delete(f"/agents/{agent['id']}/documents/{remove['id']}", headers=user_a)
    assert r.status_code == 204
    assert [d["id"] for d in await listed(client, user_a, agent["id"])] == [keep["id"]]
    assert len(await chunk_rows(db)) == 1 and len(rag.store.items) == 1


async def test_delete_refused_when_store_down(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    (doc,) = await listed(client, user_a, agent["id"])
    rag.store.fail = True
    r = await client.delete(f"/agents/{agent['id']}/documents/{doc['id']}", headers=user_a)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "vector_store_unavailable"
    assert len(await listed(client, user_a, agent["id"])) == 1
    r = await client.delete(f"/agents/{agent['id']}", headers=user_a)
    assert r.status_code == 503
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).status_code == 200


async def test_delete_agent_removes_vectors_and_chunks(client, user_a, rag, db):
    agent = await create_agent(client, user_a)
    other = await create_agent(client, user_a, name="Other")
    await paste(client, user_a, agent["id"])
    await paste(client, user_a, other["id"])
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204
    assert {m["agent_id"] for _, m in rag.store.items.values()} == {other["id"]}
    assert {str(c.agent_id) for c in await chunk_rows(db)} == {other["id"]}


async def test_delete_agent_without_documents_does_not_need_the_store(client, user_a, rag):
    agent = await create_agent(client, user_a)
    rag.store.fail = True
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204


async def test_deleted_while_processing_leaves_nothing(client, user_a, rag, db):
    from app.db.models import Document
    from app.rag.ingest import ingest_document

    agent = await create_agent(client, user_a)
    doc = Document(
        agent_id=uuid.UUID(agent["id"]), user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        filename="Gone", source_type="paste", content_hash="h", embedding_model="m", chunking_method="recursive",
    )
    db.add(doc)
    await db.commit()

    async def delete_meanwhile():
        from app.db.base import session_factory

        async with session_factory() as other:
            await other.delete(await other.get(Document, doc.id))
            await other.commit()

    rag.embedder.before_return = delete_meanwhile
    await ingest_document(doc.id, TEXT.encode(), embedder=rag.embedder, store=rag.store)
    assert await chunk_rows(db) == [] and rag.store.items == {}


async def test_sweep_marks_interrupted(client, user_a, rag, db):
    from app.db.models import Document
    from app.rag.ingest import sweep_interrupted_documents

    agent = await create_agent(client, user_a)
    for status in ("pending", "processing", "ready"):
        db.add(Document(
            agent_id=uuid.UUID(agent["id"]), user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            filename=status, source_type="paste", content_hash=status, status=status,
            embedding_model="m", chunking_method="recursive",
        ))
    await db.commit()
    await sweep_interrupted_documents()
    by_name = {d["filename"]: d for d in await listed(client, user_a, agent["id"])}
    assert by_name["ready"]["status"] == "ready"
    for name in ("pending", "processing"):
        assert by_name[name]["status"] == "failed"
        assert by_name[name]["error"] == "Processing was interrupted. Delete this document and add it again."


async def test_documents_other_user_404(client, user_a, user_b, rag):
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    (doc,) = await listed(client, user_a, agent["id"])
    responses = [
        await paste(client, user_b, agent["id"], text="intruder"),
        await client.get(f"/agents/{agent['id']}/documents", headers=user_b),
        await client.delete(f"/agents/{agent['id']}/documents/{doc['id']}", headers=user_b),
    ]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert len(await listed(client, user_a, agent["id"])) == 1


async def test_document_of_another_agent_404(client, user_a, rag):
    first = await create_agent(client, user_a, name="First")
    second = await create_agent(client, user_a, name="Second")
    await paste(client, user_a, first["id"])
    (doc,) = await listed(client, user_a, first["id"])
    r = await client.delete(f"/agents/{second['id']}/documents/{doc['id']}", headers=user_a)
    assert r.status_code == 404


async def test_document_text_is_never_in_list_response(client, user_a, rag):
    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    r = await client.get(f"/agents/{agent['id']}/documents", headers=user_a)
    assert "nine in the morning" not in r.text
    assert set(r.json()[0]) == {"id", "filename", "source_type", "status", "error", "chunk_count", "created_at"}
