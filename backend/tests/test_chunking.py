import pytest

LONG = " ".join(f"Sentence number {i} talks about topic {i % 7} in some detail." for i in range(200))


def split(pages, method, name="Handbook.pdf"):
    from app.rag.chunking import split as _split

    return _split(pages, method, name)


def body(text: str) -> str:
    """A chunk's text without its header line."""
    return text.split("\n", 1)[1]


def test_recursive_chunks_are_bounded_and_overlap():
    chunks = split([(1, LONG)], "recursive")
    assert len(chunks) > 5
    assert all(len(body(c.content)) <= 1000 for c in chunks)
    assert all(c.context is None for c in chunks)
    first, second = body(chunks[0].content), body(chunks[1].content)
    assert first[-60:] in LONG and second[:40] in first  # the next chunk starts inside the previous one


def test_parent_child_children_are_small_and_inside_their_parent():
    chunks = split([(1, LONG)], "parent_child")
    assert all(len(body(c.content)) <= 400 for c in chunks)
    assert all(c.context and len(body(c.context)) <= 2000 for c in chunks)
    assert all(body(c.content) in body(c.context) for c in chunks)
    assert len({c.context for c in chunks}) > 1  # more than one parent


@pytest.mark.parametrize("method", ["recursive", "parent_child"])
def test_headers_and_pages_are_kept(method):
    chunks = split([(1, "Alpha text on page one."), (3, "Gamma text on page three.")], method)
    assert [c.page for c in chunks] == [1, 3]
    assert chunks[0].content.startswith("[Handbook.pdf, page 1]\n")
    assert chunks[1].content.startswith("[Handbook.pdf, page 3]\n")
    if method == "parent_child":
        assert chunks[1].context.startswith("[Handbook.pdf, page 3]\n")


def test_header_without_page():
    (chunk,) = split([(None, "Just a short note.")], "recursive", "Note")
    assert chunk.content == "[Note]\nJust a short note."
    assert chunk.page is None


@pytest.mark.parametrize("method", ["recursive", "parent_child"])
def test_one_enormous_line_is_split(method):
    chunks = split([(None, "x" * 50_000)], method)
    limit = 1000 if method == "recursive" else 400
    assert len(chunks) >= 50_000 // limit
    assert all(len(body(c.content)) <= limit for c in chunks)


def test_blank_pages_are_skipped():
    chunks = split([(1, "   \n  "), (2, "Real text.")], "recursive")
    assert [c.page for c in chunks] == [2]


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        split([(1, "text")], "magic")


async def test_retry_waits_then_succeeds():
    from app.rag.embeddings import with_rate_limit_retries

    waits, attempts = [], []

    async def sleep(seconds):
        waits.append(seconds)

    async def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota")
        return "ok"

    assert await with_rate_limit_retries(flaky, sleep=sleep) == "ok"
    assert waits == [2, 4]


async def test_retry_gives_up_with_busy_message():
    from app.rag.embeddings import with_rate_limit_retries
    from app.rag.extract import DocumentError

    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    async def always_limited():
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(DocumentError) as caught:
        await with_rate_limit_retries(always_limited, sleep=sleep)
    assert str(caught.value) == "The embedding service is busy. Delete this document and try again later."
    assert waits == [2, 4, 8, 16, 32]


async def test_other_errors_are_not_retried():
    from app.rag.embeddings import with_rate_limit_retries

    async def broken():
        raise ValueError("bad request")

    async def sleep(seconds):
        raise AssertionError("should not wait")

    with pytest.raises(ValueError):
        await with_rate_limit_retries(broken, sleep=sleep)


async def test_embedder_is_only_built_when_used():
    """Every chat asks for the embedder; an agent with no knowledge base must not need its key."""
    from app.rag.embeddings import GeminiEmbedder

    embedder = GeminiEmbedder("gemini-embedding-2", "")  # no key: must not fail here
    assert embedder.model == "gemini-embedding-2"
    with pytest.raises(Exception):
        await embedder.embed_query("hello")
