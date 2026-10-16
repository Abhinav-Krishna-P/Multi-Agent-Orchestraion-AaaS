# Stage 2, Part A Design — Knowledge Base (RAG) and the Tool Loop

Date: 2026-11-17
Status: waiting for approval

Stage 2 is built in two parts. This document covers Part A. Part B (the API tools listed in `Api txt/Api  docs.txt`) gets its own design afterwards.

The full product is described in `Project data/custom-agent-platform-project- complete architecture.md` (**the spec**) and `Project data/custom-agent-platform-design.md` (**the frontend doc**). Stage 1 is described in `docs/superpowers/specs/2026-11-16-stage-1-design.md`. Where this document disagrees with them, this document wins for Part A.

## 1. Intent

Let a user give an agent its own documents, and have the agent answer from them with citations. The agent searches its documents only when a question needs them. Each part of the pipeline is tested in LangSmith, so choices such as the chunking method are made on evidence.

| Part | Contents |
|---|---|
| **A (this document)** | The tool-calling loop, the two built-in tools, the knowledge base, the Knowledge and Tools steps in the wizard, tool activity and sources in chat, LangSmith tests |
| B | The API tools from `Api txt/Api  docs.txt` (Open-Meteo, Frankfurter, AviationStack, Finnhub, SerpApi, Serper) |

## 2. Goals

At the end of Part A, on the local machine:

1. A user switches on a knowledge base for an agent and adds documents: a text-based PDF, a `.txt` file, or text typed into a box (up to 1,000 characters).
2. Each document shows its status: Pending, Processing, Ready, or Failed with the reason.
3. In chat, the agent answers questions from the documents and shows which document (and PDF page) each answer came from.
4. An agent with a knowledge base answers only from its documents. When they have no answer it says it doesn't know, even for a general question the AI model could answer. It still replies normally to greetings and small talk, without searching.
5. The user can turn on the calculator and the date-and-time tool for an agent, and chat shows a line of activity while a tool runs.
6. A user's documents are never searched by, or shown to, another user or another agent.
7. Deleting a document or an agent removes its text and its vectors from the knowledge base. Chats keep the short excerpts already shown as sources, as they keep the agent's answers.
8. LangSmith holds a test set built from the project owner's own documents, and a comparison of recursive splitting against parent-child chunking. The better method is the default.

## 3. Non-goals for Part A

- The API tools (Part B), app connections, approve/reject, analytics.
- Re-ranking. Markdown files, images, scanned PDFs, OCR.
- pgvector. Vectors live in the project owner's self-hosted Chroma DB.
- Re-indexing existing documents when the chunking method or embedding model changes later.

## 4. Anti-goals

- No document text, vector, or search result ever crosses from one user or agent to another.
- Document content is untrusted: text inside a document must never be treated as instructions to the platform.
- No secret is committed, logged, or returned by the API. No pushing.
- Stage 1 behavior does not regress: its 126 tests keep passing.

## 5. Constraints

- The machine has 7.3 GB of memory, so heavy libraries are avoided: the thin `chromadb-client` package, not the full `chromadb`.
- Chroma is reached over HTTP at the address in `CHROMA_URL`, with no login.
- Embeddings, the LangSmith judge, and any test-set generation use the platform Gemini key. Chat replies keep using the user's own key.
- OpenAI models with tools cannot be checked without an OpenAI key (see §10).

## 6. Approaches considered

**Where keyword search (BM25) runs**

- **In our backend (chosen).** Chunk text is stored in Postgres. For a keyword search, the backend scores that agent's chunks with BM25 (the `rank_bm25` library). It works with any Chroma version and gives true BM25, as asked. Its limit: it reads all of an agent's chunks per search, which is fine for thousands of chunks and needs replacing beyond that.
- **Inside Chroma.** Only Chroma's cloud product is known to offer BM25; a self-hosted server may not. Depending on it could block the build.
- **Postgres full-text search.** Built in, but its ranking is not BM25.

**How documents are split**

Both methods are built and the test in §8.6 picks the default.

- **Recursive splitting.** Chunks of about 1,000 characters with 150 overlapping. The same chunk is searched and given to the model.
- **Parent-child.** Small chunks of about 400 characters are searched; the model is given the larger section (about 2,000 characters) each one belongs to. More precise matching with more context, at the cost of longer model input.

**Rewriting follow-up questions**

- **By the agent's own model (chosen).** The search tool's description tells the model to pass a complete, standalone question. Tool-calling models do this from the chat history already, so no extra model call, cost, or delay is added.
- **A separate rewriting call on the platform key.** An extra call on every search. Only worth adding if the LangSmith tests show follow-up questions failing.

## 7. Decisions already made by the project owner

- Three inputs: text-based PDF, `.txt`, and a text box of up to 1,000 characters.
- Test both chunking methods and use the better one.
- Gemini embeddings on the platform Gemini key.
- Hybrid search: BM25 plus cosine similarity. Self-hosted Chroma as the vector database.
- No re-ranking.
- LangSmith tests every part of the pipeline. The test documents are the project owner's own.
- Knowledge base first, API tools second.
- An agent with a knowledge base answers only from its documents; it does not fall back on the model's general knowledge.

## 8. What gets built

### 8.1 The tool loop

The stage 1 graph has one node. Part A adds a tool node: the model may ask for a tool, the tool runs, its result goes back to the model, and this repeats until the model writes its answer. A turn stops after 6 tool rounds.

- A **tool registry** holds every tool the platform writes: its name, a friendly name, a one-line description, a group, an activity label ("Searching your documents…"), and whether it reads or writes. Part B adds tools by adding registry entries.
- Part A registers two tools in the group "Basics": `calculator` (arithmetic only, evaluated safely without `eval`) and `get_current_datetime` (with an optional time zone).
- A new table `agent_tools` (spec §14) records which tools each agent has switched on. Only those are given to the model.
- Chat streams three more events (spec §12.4): `tool_start` and `tool_end` with the tool's friendly activity label and whether it succeeded, and `sources` with citations.
- A tool that fails returns a short error message to the model; it never crashes the reply.
- The assistant message row stores which tools ran and the sources shown, so they reappear after a reload. Each stored source is the document's name, the page, and an excerpt of up to 300 characters; clicking a chip shows that excerpt. No extra endpoint is needed, and a chip still works after its document is deleted. Earlier turns are replayed to the model as plain user and assistant text; tool results are not replayed.
- A reply stopped partway keeps its text, as in stage 1.

### 8.2 Adding documents

New endpoints (spec §15): `POST /agents/{id}/documents` (a file, or a title and pasted text), `GET /agents/{id}/documents`, `DELETE /agents/{id}/documents/{doc_id}`, plus `GET /tools` and `PUT /agents/{id}/tools`. `PATCH /agents/{id}` also accepts `kb_enabled` and `search_mode`.

Rules:

- Files: `.pdf` and `.txt` only, up to 10 MB, and a PDF up to 300 pages. Pasted text: 1 to 1,000 characters with a title of up to 100.
- An agent holds up to 50 documents.
- The same content added twice to one agent is refused: "This document is already in the knowledge base."
- A PDF with no extractable text fails with "This PDF has no readable text." A `.txt` file that is not valid text fails with "This file isn't readable text."

Processing runs in the background after the upload returns:

1. Status `processing`. Extract the text; a PDF keeps its page numbers.
2. Split it with the default chunking method (§8.6).
3. Put a short header (the document's name, and the page for a PDF) at the top of each chunk before embedding, as the spec asks.
4. Embed the chunks with the Gemini model named in `EMBEDDING_MODEL` (`gemini-embedding-2`), in batches of 100. A rate-limit response is retried with a growing wait, up to 5 times; after that the document fails with "The embedding service is busy. Delete this document and try again later."
5. Store each chunk's text in a new Postgres table `document_chunks`, and its vector in Chroma under the same ID, tagged with the agent, user, and document.
6. Status `ready` with the chunk count, or `failed` with a reason a user can read.

If the server restarts mid-processing, documents left in `pending` or `processing` are marked failed at startup with "Processing was interrupted. Delete this document and add it again."

The model name is stored with each document. Vectors from different models are never mixed in one Chroma collection: the collection's name includes the model.

### 8.3 Searching

The agent gets a `search_knowledge_base` tool when the agent's knowledge base is on and at least one document is ready. One search:

1. **Dense:** embed the question and ask Chroma for the 20 nearest chunks by cosine similarity, filtered to this agent.
2. **Keyword:** score this agent's chunks with BM25 and take the top 20.
3. **Merge** the two lists with Reciprocal Rank Fusion and keep the top 5. The agent's search mode can instead use dense only or keyword only; hybrid is the default.
4. **Threshold:** in hybrid and dense modes, if the best cosine similarity is below a cut-off, the tool answers that nothing relevant was found, and the agent says it doesn't know. The cut-off is tuned with the tests in §8.6. Keyword-only mode returns nothing when no chunk shares a word with the question.
5. Return the chunks to the model with their document name and page, and send the same list to the chat as `sources`.

Chunk text is wrapped so the model treats it as reference material, and the tool's description says the documents are information, not instructions.

**Answering only from documents.** When an agent's knowledge base is on and has a ready document, a fixed instruction is added after the agent's own prompt for each reply: search the knowledge base before answering any question that asks for information; answer only from what the search returns; if it returns nothing relevant, say you don't have that information, and do not answer from general knowledge; greetings, thanks, and questions about the conversation itself need no search. The instruction is added at reply time and is not written into the agent's saved prompt, so the user's prompt stays as they wrote it and turning the knowledge base off restores the stage 1 behavior. An agent with no knowledge base behaves as in stage 1.

### 8.4 Deleting

Deleting a document removes its chunks from Postgres and its vectors from Chroma. Deleting an agent does the same for all its documents. If Chroma cannot be reached, the delete is refused with a message to try again, so no vectors are left behind without an owner.

### 8.5 Frontend

Following the frontend doc §6.2 and §7, with these differences:

| Screen | Part A content |
|---|---|
| Wizard | Six steps: Basics, Behavior, Model, **Knowledge**, **Tools**, Deploy |
| Knowledge step | The switch, the three search modes (Hybrid marked "Recommended"), a drop area for `.pdf` and `.txt`, a **Paste text** dialog with a title and a 1,000-character box with a counter, and the document list with live status |
| Tools step | The "Basics" group with the calculator and the date-and-time tool. Part B adds groups |
| Deploy step | Adds a Knowledge row (documents count) and a Tools row, and the warning "Some documents are still being indexed." |
| Chat | An activity line per tool call that turns into ✓ or ✕, and a Sources row of chips under the answer; clicking a chip shows that chunk's text |

The note under the drop area reads: "Text files and text-based PDFs. Scanned PDFs and images aren't supported yet."

### 8.6 LangSmith tests

The project owner puts their test documents in `Project data/rag-test-docs/` (git-ignored, since they may be private).

- **Test set:** about 25 questions written from those documents, each with the expected answer and the passage it comes from, plus a few questions the documents cannot answer. Stored as a LangSmith dataset.
- **Chunking:** the same documents are indexed once per method, and each is scored on whether the search returns the right passage in its top 5 (the hit rate, over the answerable questions). The method with the higher hit rate becomes the default. If the two are within two questions of each other, that is a tie, and recursive splitting wins because it sends less text to the model on the user's own key.
- **Search:** dense, keyword, and hybrid are scored on the same measure. This checks that hybrid earns its place as the default and tunes the threshold.
- **Answers:** the full agent is scored by a Gemini judge on whether each answer is correct and whether it is supported by the retrieved text. The unanswerable questions include general-knowledge ones (such as a capital city), and the agent passes those only by saying it doesn't have the information.
- **Tracing:** with `LANGSMITH_TRACING=true`, every step of a search (embed, dense, keyword, merge) appears as its own traced step. Tracing is a developer switch and is off by default. When it is on, traces include chat messages (as in stage 1) and the retrieved document text, so it must stay off for real users unless they are told.

The tests are scripts run by hand, not part of the automated test suite, because they call real services and cost a little.

### 8.7 Automated tests

The pytest suite covers: upload rules and limits, each failure message, ownership (a second user gets "not found" for documents and tools), both chunking methods, BM25 and the merge, the threshold, deletes reaching the vector store, the startup sweep, the tool loop with a fake model, the three new chat events, and the calculator refusing anything that is not arithmetic. Chroma and Gemini embeddings are replaced by in-memory stand-ins in these tests.

## 9. Builder's calls

Decided by the builder; each can be changed.

- BM25 runs in the backend over chunk text in Postgres (§6).
- The agent's own model writes the standalone search question; no separate rewriting call (§6).
- Limits: 10 MB per file, 300 PDF pages, 50 documents per agent, 6 tool rounds per turn.
- Chunk sizes of 1,000/150 (recursive) and 400 in 2,000 (parent-child) are starting points that the tests may change.
- Both chunking methods stay in the code behind one setting, `CHUNKING_METHOD`, after the winner is chosen.
- One Chroma collection per embedding model, filtered by agent, rather than a collection per agent.
- The calculator and date-and-time tools, the `agent_tools` table, and the Tools step are built in Part A, so Part B only adds tools.
- A delete is refused when Chroma is unreachable (§8.4).
- Tool results are not replayed to the model in later turns (§8.1).
- Documents are processed with FastAPI background tasks, as the spec says for the MVP.
- Stored sources carry a 300-character excerpt and survive the deletion of their document (§8.1).
- The rule for choosing the chunking method, including the tie-break (§8.6).
- Embedding batches of 100 with up to 5 retries on rate limits (§8.2).
- Until the project owner's test documents arrive, recursive splitting is the provisional default; the comparison runs as the last build step.

## 10. Risks

- **OpenAI models with tools are unverified.** OpenAI's documentation says GPT-6.1 Sol needs a different API for tool calls and GPT-6 Luna needs a setting changed. The builder will follow the documentation, but cannot test it without an OpenAI key.
- **The Chroma server's version is unknown** until `CHROMA_URL` is filled in. The first build step checks that it can be reached and that the client library works with it.
- **The platform Gemini key's embedding limits are unknown.** A 300-page PDF is over a thousand chunks. On a free tier, large documents may fail with the "busy" message, and the limits in §8.2 may need lowering.
- **Chroma has no login.** Anyone who can reach its address can read the vectors and chunk IDs. Chunk text stays in Postgres, which limits what is exposed.

## 11. What the project owner must provide

Put these in `backend/.env` by hand, not in chat:

1. `CHROMA_URL` — the address of the self-hosted Chroma DB.
2. `LANGSMITH_API_KEY` — and set `LANGSMITH_TRACING=true` and `LANGSMITH_PROJECT=custom-agent-platform`.

And:

3. A few of your own documents (text-based PDFs or `.txt` files) in `Project data/rag-test-docs/`.

## 12. Done means

- Every goal in §2 has been walked through in the browser.
- The automated tests pass, including all stage 1 tests.
- The LangSmith comparison has been run on the project owner's documents and its result is written into this document.

## 13. Addition (2026-11-17): chunk metadata and metadata filtering

Asked for by the project owner after approval.

- **Every chunk carries metadata:** the document's ID and name, its type (`pdf`, `txt`, `paste`), the page (for a PDF), and the chunk's position in the document. In Chroma it is stored with each vector. In Postgres it comes from the chunk's own columns and its document row, so no extra column is needed.
- **Filtered search:** the `search_knowledge_base` tool takes two optional filters, `document_name` and `page`. They narrow both the dense search (a Chroma `where` filter) and the keyword search before any ranking happens.
- **Search without similarity:** a second tool, `read_document`, returns a document's text by metadata alone: a named document, optionally one page, in reading order, up to 8 chunks per call. It serves requests like "what is on page 3 of the handbook" or "summarise the returns policy file", where ranking by similarity is the wrong tool.
- **So the model knows what it can filter on,** the reply-time instruction lists the names of the agent's ready documents.
- An unknown document name returns "There is no document with that name." and the list of names.
- The LangSmith test set gains a few questions that need a filter or a page lookup.
