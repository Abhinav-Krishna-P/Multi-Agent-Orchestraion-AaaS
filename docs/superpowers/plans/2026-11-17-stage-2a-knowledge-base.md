# Stage 2A (Knowledge Base and Tool Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user adds documents to an agent, and the agent answers only from them, with sources, through a tool-calling loop that also runs a calculator and a date tool.

**Architecture:** The stage 1 one-node LangGraph graph gains a tool node. Tools come from a registry; the knowledge-base search is one of them. Document text lives in Postgres, vectors in the owner's Chroma server, and keyword search (BM25) runs in the backend. Chroma and Gemini embeddings sit behind two small interfaces so the automated tests use in-memory stand-ins.

**Tech Stack:** As stage 1, plus `langchain-text-splitters`, `pypdf`, `python-multipart`, `chromadb-client` (thin HTTP client), `rank-bm25`, `tzdata`, LangSmith (already installed), and `react-dropzone` in the frontend.

**Spec:** `docs/superpowers/specs/2026-11-17-stage-2a-knowledge-base-design.md` (the design). It defers to the stage 1 design and to the two documents in `Project data/`.

## Global Constraints

- Everything in the stage 1 plan's Global Constraints still holds (Python via `backend/.venv`, no secrets committed or logged, no `git push`, every query filtered by the token's user ID, error body `{"detail": {"code", "message"}}`, copy rules, four states per screen, commit trailer `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`).
- Work on branch `stage-2`. The 126 stage 1 tests keep passing.
- Chroma: `CHROMA_URL` (server version 1.0.0, no login, default tenant and database). Only `chromadb-client` is installed, never the full `chromadb` package.
- Embeddings, the LangSmith judge, and test-set generation use `PLATFORM_GEMINI_API_KEY`. Chat replies use the user's own key.
- Automated tests never call Chroma, Gemini, or LangSmith. The eval scripts in Task 7 do, and are run by hand.
- Exact limits: file 10 MB; PDF 300 pages; pasted text 1–1,000 characters; title 1–100; 50 documents per agent; 6 tool rounds per turn; dense top 20, keyword top 20, merged top 5; stored source excerpt 300 characters; embedding batches of 100 with up to 5 retries.
- Exact copy: "This PDF has no readable text." · "This file isn't readable text." · "This document is already in the knowledge base." · "Processing was interrupted. Delete this document and add it again." · "The embedding service is busy. Delete this document and try again later." · "Text files and text-based PDFs. Scanned PDFs and images aren't supported yet." · "Some documents are still being indexed."

## Review Focus

1. **A PDF where only some pages have text.** The pages with text are indexed; it fails only when no page has any. (Task 4)
2. **The vector store is unreachable.** An upload ends as Failed with a readable reason; a search returns an error line to the model and the reply still finishes; a delete is refused with "try again". (Tasks 4, 5)
3. **A document is deleted while it is still being processed.** Processing stops quietly and leaves no chunks or vectors behind. (Task 4)
4. **The model misuses tools.** It asks for a tool that is not switched on, sends bad arguments, or keeps calling tools: each gets an error line back, and the turn ends after 6 rounds with a normal reply or the standard model error. (Task 3)
5. **Text that defeats the splitter or the keyword search.** A file that is one enormous line, a question with no words in common with any chunk, and a question made only of punctuation all return without error. (Tasks 4, 5)

---

## File Structure

```
backend/
  alembic/versions/0002_stage2a_knowledge_base.py
  app/
    core/config.py            # + chroma_url, embedding_model, chunking_method
    db/models.py              # + AgentTool, Document, DocumentChunk; Message.sources
    tools/registry.py         # ToolSpec, REGISTRY, catalog(), build_tools()
    tools/builtin.py          # calculator, get_current_datetime
    tools/knowledge_base.py   # search_knowledge_base tool
    rag/extract.py            # PDF / txt / pasted text -> pages of text
    rag/chunking.py           # recursive and parent-child splitting
    rag/embeddings.py         # Embedder interface + Gemini implementation
    rag/vector_store.py       # VectorStore interface + Chroma implementation
    rag/ingest.py             # background processing of one document
    rag/retrieve.py           # dense, BM25, merge, threshold
    api/tools.py              # GET /tools, PUT /agents/{id}/tools
    api/documents.py          # upload, list, delete
    agent/graph.py            # + tool node
    agent/runner.py           # + tool_start, tool_end, sources; saves tools and sources
    agent/context.py          # + reply-time instruction
    api/chat.py               # loads the agent's tools
  evals/                      # LangSmith scripts, run by hand
    build_dataset.py  run_chunking.py  run_search.py  run_answers.py  README.md
  tests/fakes.py              # + FakeEmbedder, FakeVectorStore, tool-calling scripted model
  tests/test_tools.py  test_tool_loop.py  test_documents.py  test_chunking.py  test_retrieve.py
frontend/src/
  pages/AgentWizard/Knowledge.jsx  Tools.jsx        # new steps
  components/DocumentUpload.jsx  ToolGroupList.jsx
  components/chat/ToolActivity.jsx  Sources.jsx
  lib/queries.js  lib/sse.js  pages/Chat.jsx  pages/AgentWizard/index.jsx  Deploy.jsx   # extended
```

## API contract additions

| Shape | Fields |
|---|---|
| `Agent` | adds `kb_enabled: bool`, `search_mode: "semantic"\|"keyword"\|"hybrid"`, `tools: list[str]` (enabled registry tool names) |
| `ToolCatalog` | `{groups: [{name, tools: [{name, label, description}]}]}` |
| `Document` | `id, filename, source_type ("pdf"\|"txt"\|"paste"), status ("pending"\|"processing"\|"ready"\|"failed"), error, chunk_count, created_at` |
| `Source` | `document_name, page (int or null), excerpt` |
| `Message` | adds `tools: list[{label, ok}]`, `sources: list[Source]` |

Stream events added: `tool_start {id, label}`, `tool_end {id, ok}`, `sources {sources: list[Source]}` (sent once, before `done`, only when a search returned chunks).

New error codes: `invalid_document` (422), `document_limit` (409), `duplicate_document` (409), `vector_store_unavailable` (503), `invalid_tools` (422).

---

### Task 1: Dependencies, settings, tables, and a live Chroma check

**Files:** `backend/requirements.txt`, `backend/app/core/config.py`, `backend/.env.example`, `backend/app/db/models.py`, `backend/alembic/versions/0002_stage2a_knowledge_base.py`, `backend/tests/test_health.py`

**Interfaces — Produces:**
- Settings: `chroma_url: str = ""`, `embedding_model: str = "gemini-embedding-2"`, `chunking_method: str = "recursive"` (`recursive` or `parent_child`).
- `AgentTool(id, agent_id FK cascade, tool_name, created_at)`, unique `(agent_id, tool_name)`. `Agent.tool_rows` relationship loaded with the agent; `Agent.tools -> list[str]` property (sorted names).
- `Document(id, agent_id FK cascade, user_id FK cascade, filename, source_type, status default "pending", error, content_hash, chunk_count default 0, embedding_model, chunking_method, created_at)`, check constraints on `source_type` and `status`, unique `(agent_id, content_hash)`, index on `agent_id`.
- `DocumentChunk(id, document_id FK cascade, agent_id, chunk_index, content, context, page, created_at)`, index on `agent_id`. `content` is the text that is searched; `context` is the text given to the model (null means use `content`).
- `Message.sources` (JSONB, null). `Message.tool_calls` (exists) holds `[{label, ok}]`.

- [ ] **Step 1:** Add the six packages to `requirements.txt` and install them. Confirm `pip list` shows `chromadb-client` and not `chromadb`.
- [ ] **Step 2: Failing test** in `test_health.py`: `test_stage2a_tables_exist` asserts `{"agent_tools", "documents", "document_chunks"}` are tables and `messages` has a `sources` column. Run; expect FAIL.
- [ ] **Step 3:** Add the settings and models; `alembic revision --autogenerate --rev-id 0002`; read the migration for the constraints above; `alembic upgrade head` on `agent_platform`. Run the test; expect PASS.
- [ ] **Step 4: Live Chroma check** (by hand, not a test): with `chromadb.HttpClient` on `CHROMA_URL`, create collection `connection_check` with cosine space, add two 3-number vectors with `agent_id` metadata, query with a `where` filter on `agent_id`, confirm the filtered result, delete the collection. Expected: the nearest ID comes back and the server lists no collections afterwards.
- [ ] **Step 5:** Run the whole suite (expect 127 passed) and commit `feat: stage 2A tables, settings and RAG dependencies`.

### Task 2: Tool registry, built-in tools, and switching tools on

**Files:** `backend/app/tools/__init__.py`, `registry.py`, `builtin.py`, `backend/app/api/tools.py`, `backend/app/api/schemas.py`, `backend/app/api/agents.py`, `backend/app/main.py`, `backend/tests/test_tools.py`

**Interfaces — Produces:**
- `ToolSpec(name, label, description, group, activity, access="read", tool: BaseTool)`; `REGISTRY: dict[str, ToolSpec]`; `catalog() -> dict` in the `ToolCatalog` shape, groups in registration order; `get_spec(name) -> ToolSpec | None`.
- `calculator(expression: str) -> str`: arithmetic only (`+ - * / // % **`, parentheses, unary minus, numbers, and `sqrt abs round min max`), parsed with `ast`, never `eval`. Anything else returns `"I can only do arithmetic."`; division by zero returns `"That divides by zero."`; an exponent above 1000 is refused. Label "Calculator", activity "Calculating…", group "Basics".
- `get_current_datetime(timezone: str = "UTC") -> str`: ISO date, time, weekday and zone name; an unknown zone returns `"I don't know the time zone '<x>'."`. Label "Current date and time", activity "Checking the date and time…", group "Basics".
- `GET /tools -> ToolCatalog`. `PUT /agents/{agent_id}/tools` with `{"tools": [names]}` replaces the agent's enabled set and returns `Agent`; an unknown name is 422 `invalid_tools`.
- `AgentOut` gains `kb_enabled`, `search_mode`, `tools`. `AgentUpdate` accepts `kb_enabled: bool` and `search_mode` (422 for any other value).

- [ ] **Step 1: Failing tests** in `test_tools.py`:

```python
@pytest.mark.parametrize("expr, out", [("2+2", "4"), ("(3+4)*2", "14"), ("2**10", "1024"), ("sqrt(16)", "4.0"), ("7/2", "3.5"), ("-3+1", "-2")])
def test_calculator(expr, out): assert calculator.invoke({"expression": expr}) == out
@pytest.mark.parametrize("expr", ["__import__('os').system('x')", "open('f')", "a+1", "2+", "'a'*3", "9**9**9", ""])
def test_calculator_refuses_non_arithmetic(expr): ...   # returns a refusal string, never raises
def test_calculator_divide_by_zero(): ...
def test_datetime_known_zone(): ...     # "Asia/Kolkata" -> contains "IST" or "+05:30" and a weekday name
def test_datetime_unknown_zone(): ...
async def test_catalog_lists_basics(client, user_a): ...          # one group "Basics" with both tools, each with label and description
async def test_set_tools(client, user_a): ...                     # PUT ["calculator"] -> agent["tools"] == ["calculator"]; PUT [] clears
async def test_unknown_tool_422(...): ...                         # invalid_tools, nothing changed
async def test_tools_other_user_404(...): ...
async def test_agent_shows_kb_fields(...): ...                    # kb_enabled False, search_mode "hybrid", tools []
async def test_patch_kb_fields(...): ...                          # kb_enabled true + search_mode "keyword" saved; "fuzzy" -> 422
```

- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run the suite; expect PASS. **Step 5:** Commit `feat: tool registry, calculator and date tools`.

### Task 3: The tool loop in chat

**Files:** `backend/app/agent/graph.py`, `runner.py`, `context.py`, `llm.py`, `backend/app/api/chat.py`, `backend/app/api/schemas.py`, `backend/tests/fakes.py`, `backend/tests/test_tool_loop.py`

**Interfaces:**
- Consumes: `REGISTRY`, `Agent.tools`.
- Produces:
  - `build_graph(model, tools: list[BaseTool] = ()) -> CompiledStateGraph`: with no tools it is the stage 1 graph; with tools the model is bound to them and a `ToolNode(tools, handle_tool_errors=True)` named `tools` loops back to `agent`.
  - `run_turn(*, session_id, system_prompt, summary, model, tools=(), labels: dict[str, str] = {}, extra_instruction: str | None = None)`. Runs with `recursion_limit` set so at most 6 tool rounds happen; hitting the limit is reported as the standard `model_error`.
  - Events: `tool_start` when the model asks for a tool (label from `labels`, falling back to the tool name), `tool_end` when its result arrives (`ok` is false when the tool message has error status), `sources` once before `done` with every source collected from tool results' `artifact`.
  - The saved assistant row gets `tool_calls=[{label, ok}]` and `sources=[...]`; `MessageOut` exposes them as `tools` and `sources` (empty lists when null).
  - `build_messages(system_prompt, summary, history, extra_instruction=None)`: the instruction is appended to the system message after a blank line.
  - `build_chat_model`: for provider `openai`, pass `use_responses_api=True` (OpenAI's documentation requires it for tool calls on the catalog's models; unverified without a key).
  - `chat.py`: builds the tool list from `agent.tools` through the registry and passes `labels` (tool name → activity). Task 5 adds the knowledge-base tool here.
- `tests/fakes.py`: `tool_calling(*turns)` — a scripted model whose turns are either a list of text chunks or `{"tool": name, "args": {...}}`, and which supports `bind_tools`.

- [ ] **Step 1: Failing tests** in `test_tool_loop.py` (fixtures from `test_chat.py`):

```python
async def test_tool_runs_and_answer_streams(...):
    # agent has calculator on; model: call calculator("6*7") then say "It is 42."
    # events in order: tool_start{label "Calculating…"}, tool_end{ok True}, tokens "It is 42.", done
    # the model's second call received a ToolMessage with content "42"
    # saved assistant row: content "It is 42.", tools == [{"label": "Calculating…", "ok": True}], sources == []
async def test_tool_not_enabled_is_not_offered(...): ...      # calculator off -> model called with no tools bound
async def test_unknown_tool_call_gets_error_and_reply_finishes(...): ...   # Review Focus 4: tool_end ok False, reply still saved
async def test_bad_arguments_get_error_and_reply_finishes(...): ...        # Review Focus 4
async def test_endless_tool_calls_end_as_model_error(...): ...             # 7 tool turns -> error then done; user row only
async def test_no_tools_behaves_like_stage_1(...): ...
async def test_messages_endpoint_returns_tools_and_sources(...): ...
async def test_extra_instruction_is_appended_to_system_prompt(): ...       # unit test of build_messages
async def test_stop_mid_tool_turn_saves_partial_text(...): ...             # direct run_turn, as stage 1
```

- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run the suite; expect PASS. **Step 5:** A real check by hand: with the platform Gemini key, one `run_turn` on `gemini-3.5-flash-lite` with the calculator on and the question "What is 1234 * 5678?"; expected: a `tool_start`, a `tool_end` with ok true, and an answer containing 7006652. **Step 6:** Commit `feat: tool-calling loop in chat`.

### Task 4: Adding, processing, and deleting documents

**Files:** `backend/app/rag/__init__.py`, `extract.py`, `chunking.py`, `embeddings.py`, `vector_store.py`, `ingest.py`, `backend/app/api/documents.py`, `backend/app/api/agents.py` (delete path), `backend/app/api/schemas.py`, `backend/app/main.py` (router, startup sweep), `backend/tests/fakes.py`, `backend/tests/test_chunking.py`, `backend/tests/test_documents.py`

**Interfaces — Produces:**
- `extract_pages(source_type, data: bytes) -> list[tuple[int | None, str]]`; raises `DocumentError(message)` with the exact copy for an unreadable PDF or text file, and for a PDF over 300 pages ("This PDF has more than 300 pages."). Text files are decoded as UTF-8 (with or without a BOM) only.
- `Chunk(content, context, page)`; `split(pages, method, document_name) -> list[Chunk]`. Recursive: `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)` per page. Parent-child: parents of 2000 with no overlap, children of 400 with 50 overlap inside each parent; `content` is the child, `context` the parent. Every `content` and `context` starts with the header line `[{document_name}, page {n}]` (or `[{document_name}]` when there is no page).
- `Embedder` protocol: `async embed_documents(texts) -> list[list[float]]`, `async embed_query(text) -> list[float]`, `model: str`. `GeminiEmbedder` uses `GoogleGenerativeAIEmbeddings` with the platform key, batches of 100, and up to 5 retries on a rate-limit error with waits of 2, 4, 8, 16, 32 seconds, then `DocumentError` with the "busy" copy. `get_embedder()` dependency.
- `VectorStore` protocol: `async add(ids, vectors, agent_id, document_id)`, `async query(vector, agent_id, k) -> list[tuple[str, float]]` (chunk ID, cosine similarity, best first), `async delete_document(document_id)`, `async delete_agent(agent_id)`. `ChromaVectorStore` uses one collection named `chunks_{embedding_model}` (characters outside `[a-zA-Z0-9_-]` replaced by `_`) with cosine space, and runs the synchronous client in a thread. Any client failure raises `VectorStoreUnavailable`. `get_vector_store()` dependency.
- `async ingest_document(document_id, data: bytes, *, embedder, store) -> None` (the steps of design §8.2). It re-reads the document row before writing chunks and before finishing; if the row is gone it deletes any vectors it added and returns.
- `sweep_interrupted_documents()` run at startup: `pending` and `processing` rows become `failed` with the "interrupted" copy.
- Endpoints: `POST /agents/{id}/documents` (multipart `file`, or form fields `title` + `text`) → 201 `Document` with status `pending`, processing scheduled with `BackgroundTasks`; `GET /agents/{id}/documents` newest first; `DELETE /agents/{id}/documents/{doc_id}` → 204.
- Deletes: a document delete calls `store.delete_document` first; an agent delete calls `store.delete_agent` first when the agent has any document. `VectorStoreUnavailable` → 503 `vector_store_unavailable` "The knowledge base can't be reached right now. Try again in a moment." and nothing is deleted.
- `tests/fakes.py`: `FakeEmbedder` (a deterministic vector from word counts, so texts sharing words are closer) and `FakeVectorStore` (in memory, real cosine, a `fail` switch).

- [ ] **Step 1: Failing tests** in `test_chunking.py`: recursive chunks are ≤ 1000 characters plus header and overlap by shared text; parent-child `content` ≤ 400 plus header and each `context` contains its child's text; page numbers are kept; headers are present; a one-line 50,000-character text splits without error (Review Focus 5); empty pages are skipped.
- [ ] **Step 2: Failing tests** in `test_documents.py` (PDFs are built in the test with `pypdf`'s writer plus a minimal text page helper, or loaded from small fixture bytes):

```python
async def test_paste_text_becomes_ready(...): ...           # 201 pending -> after background: ready, chunk_count >= 1, chunks in DB and store
async def test_txt_upload_becomes_ready(...): ...
async def test_pdf_upload_keeps_pages(...): ...             # chunk.page set
async def test_pdf_with_some_empty_pages_is_indexed(...): ...   # Review Focus 1
async def test_pdf_without_text_fails(...): ...             # failed, "This PDF has no readable text."
async def test_binary_txt_fails(...): ...                   # "This file isn't readable text."
@pytest.mark.parametrize(...)                                # wrong extension, 10 MB + 1 byte, empty paste, 1001 chars, title 101 chars, neither file nor text
async def test_invalid_upload_422(...): ...                  # invalid_document, no row
async def test_paste_of_exactly_1000_chars_accepted(...): ...
async def test_duplicate_refused(...): ...                   # 409 duplicate_document; same content on another agent is fine
async def test_document_limit(...): ...                      # 51st -> 409 document_limit
async def test_embedding_busy_marks_failed(...): ...         # embedder raising the busy DocumentError
async def test_store_down_marks_failed(...): ...             # Review Focus 2
async def test_delete_document_removes_chunks_and_vectors(...): ...
async def test_delete_refused_when_store_down(...): ...      # 503, row still there   (Review Focus 2)
async def test_delete_agent_removes_vectors(...): ...
async def test_deleted_while_processing_leaves_nothing(...): ...   # Review Focus 3
async def test_sweep_marks_interrupted(...): ...
async def test_documents_other_user_404(...): ...            # upload, list, delete
async def test_document_text_is_never_in_list_response(...): ...
```

- [ ] **Step 3:** Run; expect FAIL. **Step 4:** Implement. **Step 5:** Run the suite; expect PASS.
- [ ] **Step 6: Live check by hand:** ingest `Project data/rag-test-docs/textfile.txt` for a throwaway agent on the test database with the real embedder and real Chroma; expected: status ready, the Chroma collection holds the same number of items as `document_chunks`; then delete the agent and confirm the collection count returns to zero.
- [ ] **Step 7:** Commit `feat: knowledge base documents, processing and deletion`.

### Task 5: Search and the knowledge-base tool

**Files:** `backend/app/rag/retrieve.py`, `backend/app/tools/knowledge_base.py`, `backend/app/api/chat.py`, `backend/tests/test_retrieve.py`, `backend/tests/test_tool_loop.py`

**Interfaces — Produces:**
- `tokenize(text) -> list[str]` (lower-cased `\w+`).
- `bm25_search(chunks: list[tuple[id, text]], query, k=20) -> list[id]`: `BM25Okapi`; chunks scoring 0 are left out; an empty token list returns `[]`.
- `rrf(*rankings: list[id], k=60) -> list[id]`.
- `Hit(chunk_id, document_name, page, text, similarity)`; `async search(agent_id, query, mode, *, db, embedder, store, min_similarity) -> list[Hit]` implementing design §8.3 and returning at most 5 hits, where `text` is the chunk's `context` or `content`. Constant `MIN_SIMILARITY = 0.35`, tuned in Task 7. Each step (`embed_query`, `dense`, `keyword`, `merge`) is wrapped with LangSmith's `traceable`.
- `build_kb_tool(agent_id, mode, ...) -> BaseTool` named `search_knowledge_base` with one argument `query`, returning content and artifact: content is the hits wrapped as `<document name="…" page="…">…</document>` blocks, or `"No relevant information was found in the knowledge base."`; the artifact is the list of `Source` dicts (excerpt = the first 300 characters of the hit text without its header). A `VectorStoreUnavailable` or embedding failure returns `"The knowledge base could not be searched right now."` with no artifact.
- `KB_INSTRUCTION`: the reply-time instruction of design §8.3.
- `chat.py`: when `agent.kb_enabled` and the agent has at least one `ready` document, add the tool, its activity label "Searching your documents…", and pass `extra_instruction=KB_INSTRUCTION`.

- [ ] **Step 1: Failing tests** in `test_retrieve.py`: BM25 ranks the chunk with the query's rare word first; zero-score chunks are dropped; a punctuation-only query returns `[]` (Review Focus 5); `rrf` puts an item ranked high in both lists first and keeps items found by only one; `search` in each of the three modes returns the expected chunk from a small seeded set; hybrid below the threshold returns `[]`; keyword mode with no shared word returns `[]`; another agent's chunks never appear; parent-child rows return `context`; at most 5 hits.
- [ ] **Step 2: Failing tests** added to `test_tool_loop.py`: a scripted model calls `search_knowledge_base` and the stream carries `sources` before `done` with `document_name`, `page`, `excerpt` (≤ 300 characters); the saved row has the sources; the system message contains `KB_INSTRUCTION` only when the knowledge base is on with a ready document; with the store failing, `tool_end` has ok false… and the reply still finishes (Review Focus 2); the tool is not offered when the agent has no ready document.
- [ ] **Step 3:** Run; expect FAIL. **Step 4:** Implement. **Step 5:** Run the suite; expect PASS. **Step 6:** Commit `feat: hybrid search and knowledge-base tool`.

### Task 6: Frontend — Knowledge and Tools steps, tool activity, sources

**Files:** `frontend/src/lib/queries.js`, `lib/sse.js`, `lib/api.js` (multipart upload helper), `pages/AgentWizard/index.jsx`, `Knowledge.jsx`, `Tools.jsx`, `Deploy.jsx`, `components/DocumentUpload.jsx`, `components/ToolGroupList.jsx`, `components/chat/ToolActivity.jsx`, `Sources.jsx`, `Message.jsx`, `MessageList.jsx`, `pages/Chat.jsx`

- [ ] **Step 1:** `npm install react-dropzone`; add shadcn `switch`, `checkbox`, `popover`.
- [ ] **Step 2: Wizard.** Steps become Basics, Behavior, Model, Knowledge, Tools, Deploy.
  - Knowledge: the "Use a knowledge base" switch (saves `kb_enabled` at once); when on, the three search modes as radio cards with one line each (Hybrid marked "Recommended"), the drop area for `.pdf` and `.txt` (client-side check of type and 10 MB before upload), a "Paste text" dialog (title, a text area with a live `n/1,000` counter, the button disabled over the limit), the fixed note from Global Constraints, and the document list: name, type, status badge (Pending and Processing amber, Ready green, Failed red with its reason), chunk count when ready, Delete with confirmation. The list refetches every 3 seconds while any document is Pending or Processing.
  - Tools: checkbox list from `GET /tools`, grouped, with "Select all" per group; Continue saves with `PUT /agents/{id}/tools`.
  - Deploy: adds a Knowledge row ("Off", or "On · n documents") and a Tools row ("n tools"), and the warning "Some documents are still being indexed." while any is not Ready or Failed.
- [ ] **Step 3: Chat.** `streamChat` passes `tool_start`, `tool_end`, `sources` to new callbacks. While streaming, each tool shows as a line with its label and a spinner that becomes ✓ or ✕ (with the words "Done" / "Failed" for screen readers). Saved messages show their tools the same way and a "Sources" row of chips (`document_name`, and `p. n` when there is a page); a chip opens a popover with the excerpt.
- [ ] **Step 4:** `npm run build` and `npm run lint`; expected: both clean. **Step 5:** Commit `feat: knowledge and tools steps, tool activity and sources in chat`.

### Task 7: LangSmith tests on the owner's documents

**Files:** `backend/evals/__init__.py`, `common.py`, `build_dataset.py`, `run_chunking.py`, `run_search.py`, `run_answers.py`, `README.md`; the design document (results section); `backend/app/core/config.py` and `retrieve.py` if the results change a default.

- [ ] **Step 1: `build_dataset.py`.** Reads every file in `Project data/rag-test-docs/`, and with the platform Gemini model drafts 25 answerable questions (each with `answer` and the exact `evidence` sentence copied from the document) and 5 unanswerable ones (3 on topics near the documents, 2 general knowledge). It checks every `evidence` string really occurs in the extracted text and drops any that do not, then creates or replaces the LangSmith dataset `rag-test-docs`. Run it and read the questions; fix or drop poor ones by hand in LangSmith.
- [ ] **Step 2: `run_chunking.py`.** For each method, index the documents for a throwaway agent on the test database (real embedder, real Chroma), then run a LangSmith experiment over the answerable questions with the target "hybrid search" and the evaluator `evidence_found` (true when the evidence sentence, whitespace-normalised, is inside any returned hit's text). Prints both hit rates and applies the design's rule (higher wins; within two questions, recursive). Cleans up its agents and vectors.
- [ ] **Step 3: `run_search.py`.** With the winning method: experiments for dense, keyword, and hybrid with the same evaluator; and for the unanswerable questions the share where the search returns nothing, across thresholds 0.25, 0.30, 0.35, 0.40, 0.45. Choose the threshold that keeps the answerable hit rate within one question of its best while rejecting the most unanswerable ones.
- [ ] **Step 4: `run_answers.py`.** Runs the full agent (the tool loop on `gemini-3.5-flash-lite` with the platform key) on all 30 questions. Evaluators: `correct` (a Gemini judge comparing with the reference answer), `grounded` (the judge checks the answer against the retrieved text), and `declined` for the unanswerable ones (the answer says it does not have the information).
- [ ] **Step 5:** Set `CHUNKING_METHOD`'s default and `MIN_SIMILARITY` to the winners, re-run the test suite, and write a "Results" section into the design document with the numbers and the LangSmith experiment names.
- [ ] **Step 6:** Commit `feat: LangSmith evaluation of chunking, search and answers`.

### Task 8: Walkthrough

- [ ] **Step 1:** Whole backend suite, frontend build and lint; expected: all clean.
- [ ] **Step 2:** In the browser, with the owner: every goal in design §2, including a PDF and a pasted text, a question answered with sources, a general-knowledge question declined, a greeting answered without a search, the calculator, deleting a document, and a second look in LangSmith at one traced search.
- [ ] **Step 3:** Fix anything found (each backend fix with a test first), then re-run Step 1. Commit. Do not push.
