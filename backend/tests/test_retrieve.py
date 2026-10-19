import uuid

import pytest

from tests.fakes import scripted
from tests.rag_fakes import make_pdf
from tests.test_agents import create_agent
from tests.test_chat import live_chat, read_events, send, tokens, use_model  # noqa: F401  (fixtures)
from tests.test_documents import paste, rag, upload  # noqa: F401  (fixtures)
from tests.test_tool_loop import call, saved_rows

HOURS = "Our store opens at nine in the morning and closes at six in the evening on weekdays."
RETURNS = "Returns are accepted within thirty days when the customer brings the original receipt."
SHIPPING = "Standard shipping takes five business days and costs four dollars."


# --- the pure pieces -------------------------------------------------------------------


def test_tokenize():
    from app.rag.retrieve import tokenize

    assert tokenize("Hello, World! It's 9am.") == ["hello", "world", "it", "s", "9am"]
    assert tokenize("?!... --") == []


def test_bm25_ranks_the_rare_word_first_and_drops_non_matches():
    from app.rag.retrieve import bm25_search

    chunks = [("a", HOURS), ("b", RETURNS), ("c", SHIPPING), ("d", "The store has a car park behind the building.")]
    assert bm25_search(chunks, "original receipt for returns")[0] == "b"
    assert bm25_search(chunks, "store") == ["d", "a"] or set(bm25_search(chunks, "store")) == {"a", "d"}
    assert bm25_search(chunks, "zebra") == []
    assert bm25_search(chunks, "?!...") == []
    assert bm25_search([], "store") == []


def test_bm25_works_with_a_single_chunk():
    from app.rag.retrieve import bm25_search

    assert bm25_search([("a", HOURS)], "when does the store open") == ["a"]


def test_rrf_prefers_items_ranked_high_in_both_lists():
    from app.rag.retrieve import rrf

    assert rrf(["a", "b", "c"], ["b", "a", "d"])[:2] in (["a", "b"], ["b", "a"])
    merged = rrf(["a", "b", "c"], ["c", "x"])
    assert merged[0] == "c" and set(merged) == {"a", "b", "c", "x"}
    assert rrf([], ["z"]) == ["z"]
    assert rrf([], []) == []


# --- search over real rows, with stand-in embeddings and vector store ----------------------


@pytest.fixture
async def kb(client, user_a, rag):  # noqa: F811
    """An agent with three short ready documents. Returns (agent, rag)."""
    agent = await create_agent(client, user_a)
    for title, text in (("Hours", HOURS), ("Returns", RETURNS), ("Shipping", SHIPPING)):
        assert (await paste(client, user_a, agent["id"], text=text, title=title)).status_code == 201
    return agent, rag


async def run_search(agent, rag_, query, mode="hybrid", **kwargs):
    from app.db.base import session_factory
    from app.rag.retrieve import search

    async with session_factory() as db:
        return await search(
            uuid.UUID(agent["id"]), query, mode, db=db, embedder=rag_.embedder, store=rag_.store, **kwargs
        )


@pytest.mark.parametrize("mode", ["hybrid", "semantic", "keyword"])
async def test_each_mode_finds_the_right_document(kb, mode):
    agent, rag_ = kb
    hits = await run_search(agent, rag_, "how many days does standard shipping take", mode, min_similarity=0.05)
    assert hits[0].document_name == "Shipping"
    assert hits[0].text == f"[Shipping]\n{SHIPPING}"
    assert hits[0].page is None


async def test_hybrid_below_the_threshold_returns_nothing(kb):
    agent, rag_ = kb
    assert await run_search(agent, rag_, "zebra quantum violin", "hybrid", min_similarity=0.05) == []
    assert await run_search(agent, rag_, "store opens", "hybrid", min_similarity=0.99) == []


async def test_keyword_mode_with_no_shared_word_returns_nothing(kb):
    agent, rag_ = kb
    assert await run_search(agent, rag_, "zebra quantum violin", "keyword") == []
    assert await run_search(agent, rag_, "?!...", "keyword") == []


async def test_at_most_five_hits(client, user_a, rag):  # noqa: F811
    agent = await create_agent(client, user_a)
    for i in range(8):
        await paste(client, user_a, agent["id"], text=f"The store sells item number {i} for ten dollars.", title=f"Item {i}")
    hits = await run_search(agent, rag, "what does the store sell", "hybrid", min_similarity=0.05)
    assert len(hits) == 5


async def test_another_agents_documents_never_appear(client, user_a, kb, rag):  # noqa: F811
    _, rag_ = kb
    other = await create_agent(client, user_a, name="Other")
    await paste(client, user_a, other["id"], text="Completely different agent text about shipping days.", title="Private")
    for mode in ("hybrid", "semantic", "keyword"):
        hits = await run_search(kb[0], rag_, "shipping days", mode, min_similarity=0.05)
        assert hits and all(h.document_name != "Private" for h in hits)


async def test_documents_that_are_not_ready_are_ignored(client, user_a, kb, db):
    from sqlalchemy import update

    from app.db.models import Document

    agent, rag_ = kb
    await db.execute(update(Document).where(Document.filename == "Shipping").values(status="failed"))
    await db.commit()
    hits = await run_search(agent, rag_, "standard shipping business days", "hybrid", min_similarity=0.05)
    assert all(h.document_name != "Shipping" for h in hits)


async def test_filter_by_document_name_and_page(client, user_a, kb):
    agent, rag_ = kb
    pdf = make_pdf(["Shipping to Europe takes ten days.", "Shipping to Asia takes twelve days."])
    await upload(client, user_a, agent["id"], "world.pdf", pdf)
    hits = await run_search(agent, rag_, "shipping days", "hybrid", min_similarity=0.05, document_name="WORLD.pdf")
    assert hits and {h.document_name for h in hits} == {"world.pdf"}
    hits = await run_search(
        agent, rag_, "shipping days", "hybrid", min_similarity=0.05, document_name="world.pdf", page=2
    )
    assert [h.page for h in hits] == [2] and "Asia" in hits[0].text
    for mode in ("semantic", "keyword"):
        hits = await run_search(agent, rag_, "shipping days", mode, min_similarity=0.05, page=1)
        assert hits and all(h.page == 1 for h in hits)


async def test_unknown_document_name_is_reported(kb):
    from app.rag.retrieve import UnknownDocument

    agent, rag_ = kb
    with pytest.raises(UnknownDocument) as caught:
        await run_search(agent, rag_, "anything", "hybrid", document_name="Nope")
    assert caught.value.names == ["Hours", "Returns", "Shipping"]


async def test_parent_child_rows_return_the_parent_once(client, user_a, rag, db):  # noqa: F811
    from app.db.models import Document, DocumentChunk

    agent = await create_agent(client, user_a)
    agent_id = uuid.UUID(agent["id"])
    doc = Document(
        agent_id=agent_id, user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"), filename="Guide",
        source_type="paste", content_hash="h", status="ready", embedding_model="m", chunking_method="parent_child",
    )
    db.add(doc)
    await db.flush()
    parent = "[Guide]\nThe warranty lasts two years. Batteries are covered for one year only."
    children = ["[Guide]\nThe warranty lasts two years.", "[Guide]\nBatteries are covered for one year only."]
    for index, child in enumerate(children):
        chunk = DocumentChunk(document_id=doc.id, agent_id=agent_id, chunk_index=index, content=child, context=parent)
        db.add(chunk)
        await db.flush()
        await rag.store.add(
            [str(chunk.id)], await rag.embedder.embed_documents([child]),
            [{"agent_id": agent["id"], "document_id": str(doc.id), "document_name": "Guide", "source_type": "paste", "chunk_index": index}],
        )
    await db.commit()
    hits = await run_search(agent, rag, "how long is the warranty for batteries", "hybrid", min_similarity=0.05)
    assert [h.text for h in hits] == [parent]


async def test_read_document_returns_chunks_in_order_without_similarity(client, user_a, kb, db):
    from app.rag.retrieve import UnknownDocument, read_document

    agent, _ = kb
    pdf = make_pdf([f"Page {n} says the code is {n * 111}." for n in range(1, 13)])
    await upload(client, user_a, agent["id"], "codes.pdf", pdf)
    agent_id = uuid.UUID(agent["id"])
    hits = await read_document(agent_id, "codes.pdf", None, db=db)
    assert [h.page for h in hits] == [1, 2, 3, 4, 5, 6, 7, 8]  # capped at 8, in reading order
    (hit,) = await read_document(agent_id, "CODES.PDF", 11, db=db)
    assert hit.page == 11 and "1221" in hit.text
    assert await read_document(agent_id, "codes.pdf", 99, db=db) == []
    with pytest.raises(UnknownDocument):
        await read_document(agent_id, "missing.pdf", None, db=db)


# --- the tools inside a chat ---------------------------------------------------------------


@pytest.fixture
async def kb_chat(client, user_a, live_chat, rag):  # noqa: F811
    """The live chat's agent with its knowledge base on and two ready documents."""
    agent, session = live_chat
    await client.patch(f"/agents/{agent['id']}", json={"kb_enabled": True}, headers=user_a)
    await paste(client, user_a, agent["id"], text=HOURS, title="Hours")
    await upload(client, user_a, agent["id"], "policy.pdf", make_pdf([RETURNS, SHIPPING]))
    return agent, session, rag


async def test_search_tool_answers_with_sources(client, user_a, kb_chat, use_model, db, monkeypatch):  # noqa: F811
    from app.rag import retrieve

    monkeypatch.setattr(retrieve, "MIN_SIMILARITY", 0.05)
    agent, session, _ = kb_chat
    model = scripted(call("search_knowledge_base", query="Are returns accepted within thirty days with the original receipt?"), ["Thirty days."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "What is the returns policy?"})
    events = read_events(r.text)
    assert [name for name, _ in events] == ["tool_start", "tool_end", "token", "sources", "done"]
    assert events[0][1]["label"] == "Searching your documents…"
    assert events[1][1]["ok"] is True
    sources = events[3][1]["sources"]
    assert sources[0] == {"document_name": "policy.pdf", "page": 1, "excerpt": RETURNS}
    assert all(len(s["excerpt"]) <= 300 and set(s) == {"document_name", "page", "excerpt"} for s in sources)
    tool_result = model.received[1][-1].content
    assert '<document name="policy.pdf" page="1">' in tool_result and RETURNS in tool_result
    assert set(model.bound) == {"search_knowledge_base", "read_document"}
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.sources == sources
    assert assistant.tool_calls == [{"label": "Searching your documents…", "ok": True}]


async def test_instruction_lists_documents_only_when_kb_is_usable(client, user_a, kb_chat, use_model):  # noqa: F811
    agent, session, _ = kb_chat
    model = scripted(["Hello."], ["Hello again."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    system = model.received[0][0].content
    assert "Answer only from what your tools return" in system
    assert "Hours" in system and "policy.pdf" in system
    await client.patch(f"/agents/{agent['id']}", json={"kb_enabled": False}, headers=user_a)
    await send(client, user_a, session["id"], {"message": "Hi again"})
    assert "Answer only from what your tools return" not in model.received[1][0].content
    assert model.bound == ["search_knowledge_base", "read_document"]  # unchanged: second reply bound no tools


async def test_kb_on_without_ready_documents_offers_no_tool(client, user_a, live_chat, rag, use_model):  # noqa: F811
    agent, session = live_chat
    await client.patch(f"/agents/{agent['id']}", json={"kb_enabled": True}, headers=user_a)
    model = scripted(["Hello."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert model.bound is None
    assert "knowledge base" not in model.received[0][0].content.lower()


async def test_nothing_found_tells_the_model_so(client, user_a, kb_chat, use_model):  # noqa: F811
    _, session, _ = kb_chat
    model = scripted(call("search_knowledge_base", query="zebra quantum violin"), ["I don't have that information."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Tell me about zebras"})
    events = read_events(r.text)
    assert [name for name, _ in events] == ["tool_start", "tool_end", "token", "done"]  # no sources event
    assert model.received[1][-1].content == "No relevant information was found in the knowledge base."


async def test_unknown_document_filter_lists_the_real_names(client, user_a, kb_chat, use_model):  # noqa: F811
    _, session, _ = kb_chat
    model = scripted(call("search_knowledge_base", query="returns", document_name="handbook.pdf"), ["Not found."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Check the handbook"})
    assert model.received[1][-1].content == (
        "There is no document with that name. The documents are: Hours, policy.pdf."
    )


async def test_read_document_tool_fetches_a_page(client, user_a, kb_chat, use_model):  # noqa: F811
    _, session, _ = kb_chat
    model = scripted(call("read_document", document_name="policy.pdf", page=2), ["Page two is about shipping."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "What is on page 2 of policy.pdf?"})
    events = read_events(r.text)
    assert events[0][1]["label"] == "Reading your documents…"
    assert SHIPPING in model.received[1][-1].content and RETURNS not in model.received[1][-1].content
    sources = next(data for name, data in events if name == "sources")["sources"]
    assert sources == [{"document_name": "policy.pdf", "page": 2, "excerpt": SHIPPING}]


async def test_search_failure_is_reported_and_the_reply_finishes(client, user_a, kb_chat, use_model, db):  # noqa: F811
    _, session, rag_ = kb_chat
    rag_.store.fail = True
    model = scripted(call("search_knowledge_base", query="returns policy"), ["I couldn't search right now."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Returns?"})
    events = read_events(r.text)
    assert events[1][1]["ok"] is False
    assert events[-1][0] == "done" and events[-1][1]["message_id"]
    assert (await saved_rows(db, session["id"]))[-1].tool_calls == [{"label": "Searching your documents…", "ok": False}]
