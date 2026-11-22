"""LangSmith tests of the knowledge base, on the owner's own documents.

Run by hand from the backend directory (they call Gemini, Chroma and LangSmith, and cost a little):

    python -m evals.run dataset     # write the test questions from the documents
    python -m evals.run chunking    # recursive vs parent-child: which finds the right passage more often
    python -m evals.run search      # semantic vs keyword vs hybrid, and the similarity cut-off
    python -m evals.run answers     # the whole agent: correct, grounded, and declines when it should

Documents are read from "Project data/rag-test-docs/". Everything is indexed for a throwaway
agent on the TEST database and removed afterwards, so real users' data is never touched.
"""
import asyncio
import hashlib
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parents[1]
_env = dotenv_values(BACKEND / ".env")
assert (_env.get("TEST_DATABASE_URL") or "").rsplit("/", 1)[-1].endswith("_test"), "TEST_DATABASE_URL must be a *_test database"
os.environ["DATABASE_URL"] = _env["TEST_DATABASE_URL"]  # before any app import: evals never use the real database
for _key in ("LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
    if _env.get(_key):
        os.environ[_key] = _env[_key]
os.environ["LANGSMITH_TRACING"] = "true"

from langchain_core.messages import ToolMessage  # noqa: E402
from langsmith import Client, aevaluate  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.agent.context import build_messages  # noqa: E402
from app.agent.graph import RECURSION_LIMIT, build_graph  # noqa: E402
from app.agent.llm import build_chat_model  # noqa: E402
from app.agent.runner import chunk_text  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.base import session_factory  # noqa: E402
from app.db.models import Agent, Document, User  # noqa: E402
from app.rag import retrieve  # noqa: E402
from app.rag.chunking import METHODS  # noqa: E402
from app.rag.embeddings import get_embedder  # noqa: E402
from app.rag.extract import extract_pages  # noqa: E402
from app.rag.ingest import ingest_document  # noqa: E402
from app.rag.vector_store import get_vector_store  # noqa: E402
from app.tools.knowledge_base import build_kb_tools, kb_instruction  # noqa: E402

DOCS = BACKEND.parent / "Project data" / "rag-test-docs"
DATASET = "rag-test-docs"
WRITER_MODEL = "gemini-3.8-flash"  # writes the questions and judges the answers
AGENT_MODEL = "gemini-3.5-flash-lite"  # the cheapest model users can pick: the hardest case
THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)

settings = get_settings()
client = Client()


def model(name: str):
    return build_chat_model("gemini", name, settings.platform_gemini_api_key)


def squash(text: str) -> str:
    """Whitespace-insensitive form, so line breaks from PDF extraction don't hide a match."""
    return re.sub(r"\s+", " ", text).strip().lower()


def load_documents() -> list[tuple[str, str, bytes, list]]:
    """(name, type, bytes, pages) for every readable test document."""
    documents = []
    for path in sorted(DOCS.iterdir()):
        source_type = {".pdf": "pdf", ".txt": "txt"}.get(path.suffix.lower())
        if not source_type:
            continue
        data = path.read_bytes()
        try:
            documents.append((path.name, source_type, data, extract_pages(source_type, data)))
        except Exception as error:
            print(f"  skipping {path.name}: {error}")
    return documents


@asynccontextmanager
async def indexed_agent(method: str):
    """A throwaway agent with every test document indexed by the given chunking method."""
    embedder, store = get_embedder(), get_vector_store()
    user_id, agent_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=user_id, email=f"eval-{user_id}@example.com"))
        await db.flush()
        db.add(Agent(id=agent_id, user_id=user_id, name=f"Eval {method}"))
        await db.commit()
    try:
        chunks = 0
        for name, source_type, data, _ in load_documents():
            async with session_factory() as db:
                document = Document(
                    agent_id=agent_id, user_id=user_id, filename=name, source_type=source_type,
                    content_hash=hashlib.sha256(data).hexdigest(), embedding_model=embedder.model,
                    chunking_method=method,
                )
                db.add(document)
                await db.commit()
                document_id = document.id
            await ingest_document(document_id, data, embedder=embedder, store=store)
            async with session_factory() as db:
                document = await db.get(Document, document_id)
                assert document.status == "ready", f"{name}: {document.error}"
                chunks += document.chunk_count
        print(f"  indexed with {method}: {chunks} chunks")
        yield SimpleNamespace(id=agent_id, embedder=embedder, store=store, chunks=chunks)
    finally:
        await store.delete_agent(agent_id)
        async with session_factory() as db:
            await db.delete(await db.get(User, user_id))
            await db.commit()


def examples(split: str) -> list:
    return list(client.list_examples(dataset_name=DATASET, splits=[split]))


async def experiment(name: str, target, data: list, evaluators: list) -> dict[str, list]:
    """Runs one LangSmith experiment and returns each evaluator's scores."""
    scores: dict[str, list] = {}

    def recorded(evaluator):
        def wrapper(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
            result = evaluator(inputs, outputs, reference_outputs)
            scores.setdefault(evaluator.__name__, []).append(result["score"])
            return {"key": evaluator.__name__, **result}

        wrapper.__name__ = evaluator.__name__
        return wrapper

    await aevaluate(
        target, data=data, evaluators=[recorded(e) for e in evaluators], experiment_prefix=name,
        max_concurrency=4, client=client,
    )
    return scores


def rate(values: list) -> str:
    return f"{sum(bool(v) for v in values)}/{len(values)}"


# --- dataset --------------------------------------------------------------------------------


class _Question(BaseModel):
    question: str
    answer: str
    evidence: str
    document: str


class _Draft(BaseModel):
    answerable: list[_Question]
    page_questions: list[_Question]
    unanswerable_related: list[str]
    unanswerable_general: list[str]


async def build_dataset() -> None:
    documents = load_documents()
    source = "\n\n".join(
        f"=== {name}{f', page {page}' if page else ''} ===\n{text}" for name, _, _, pages in documents for page, text in pages
    )
    names = [name for name, *_ in documents]
    prompt = (
        "You are writing a test set for a question-answering system over the documents below.\n"
        f"Documents: {', '.join(names)}.\n\n"
        "Write:\n"
        "- `answerable`: 25 questions a real user might ask, each answered by ONE specific passage. Spread them "
        "across all the documents and across the start, middle and end of long ones. Mix easy questions with ones "
        "that use different wording from the text, and ones that hinge on an exact name, number or code.\n"
        "- `page_questions`: 4 questions that name a document and a page, such as 'What does page 7 of X say "
        "about ...?', only for documents that have pages.\n"
        "For both kinds give `answer` (one or two sentences), `evidence` (ONE sentence copied EXACTLY, character "
        "for character, from the document, that contains the answer) and `document` (the document's name).\n"
        "- `unanswerable_related`: 3 questions on the documents' subject that the documents do NOT answer.\n"
        "- `unanswerable_general`: 2 general-knowledge questions that have nothing to do with the documents.\n\n"
        f"DOCUMENTS\n{source}"
    )
    draft: _Draft = await model(WRITER_MODEL).with_structured_output(_Draft).ainvoke(prompt)

    texts = {name: squash(" ".join(text for _, text in pages)) for name, _, _, pages in documents}
    rows, dropped = [], 0
    for kind, questions in (("fact", draft.answerable), ("page", draft.page_questions)):
        for q in questions:
            # Keep a question only if its evidence really is in the document it names.
            if q.document in texts and squash(q.evidence) in texts[q.document]:
                rows.append({
                    "inputs": {"question": q.question},
                    "outputs": {"answer": q.answer, "evidence": q.evidence, "document": q.document},
                    "metadata": {"kind": kind}, "split": "answerable",
                })
            else:
                dropped += 1
    for kind, questions in (("related", draft.unanswerable_related), ("general", draft.unanswerable_general)):
        rows += [
            {"inputs": {"question": q}, "outputs": {"answer": "(not in the documents)"},
             "metadata": {"kind": kind}, "split": "unanswerable"}
            for q in questions
        ]
    if client.has_dataset(dataset_name=DATASET):
        client.delete_dataset(dataset_name=DATASET)
    dataset = client.create_dataset(DATASET, description="Questions written from the owner's RAG test documents.")
    client.create_examples(dataset_id=dataset.id, examples=rows)
    answerable = sum(r["split"] == "answerable" for r in rows)
    print(f"dataset '{DATASET}': {answerable} answerable, {len(rows) - answerable} unanswerable; "
          f"{dropped} dropped because their evidence was not found word for word")
    for row in rows:
        print(f"  [{row['metadata']['kind']}] {row['inputs']['question']}")


# --- retrieval ------------------------------------------------------------------------------


def search_target(agent, mode: str):
    async def target(inputs: dict) -> dict:
        async with session_factory() as db:
            hits = await retrieve.search(
                agent.id, inputs["question"], mode, db=db, embedder=agent.embedder, store=agent.store, min_similarity=0.0
            )
        similarities = [h.similarity for h in hits if h.similarity is not None]
        return {"hits": [h.text for h in hits], "top_similarity": max(similarities, default=None)}

    return target


def evidence_found(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Did the search return the passage that holds the answer? (It may straddle two chunks.)"""
    evidence = squash(reference_outputs["evidence"])
    found = any(evidence in squash(hit) for hit in outputs["hits"]) or evidence in squash(" ".join(outputs["hits"]))
    return {"score": found}


def top_similarity(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    return {"score": outputs["top_similarity"] or 0.0}


async def run_chunking() -> None:
    data, results = examples("answerable"), {}
    for method in METHODS:
        async with indexed_agent(method) as agent:
            scores = await experiment(f"chunking-{method}", search_target(agent, "hybrid"), data, [evidence_found])
            results[method] = sum(scores["evidence_found"])
            print(f"  {method}: right passage found for {rate(scores['evidence_found'])} questions")
    gap = results["parent_child"] - results["recursive"]
    # The design's rule: higher wins; within two questions it is a tie, and recursive wins
    # the tie because it sends less text to the model on the user's own key.
    winner = "parent_child" if gap > 2 else "recursive"
    print(f"RESULT chunking: recursive {results['recursive']}, parent_child {results['parent_child']} "
          f"of {len(data)} -> use {winner}")


async def run_search() -> None:
    answerable, unanswerable = examples("answerable"), examples("unanswerable")
    async with indexed_agent(settings.chunking_method) as agent:
        for mode in ("semantic", "keyword", "hybrid"):
            scores = await experiment(f"search-{mode}", search_target(agent, mode), answerable, [evidence_found])
            print(f"  {mode}: right passage found for {rate(scores['evidence_found'])} questions")
        good = (await experiment("similarity-answerable", search_target(agent, "semantic"), answerable, [top_similarity]))["top_similarity"]
        bad = (await experiment("similarity-unanswerable", search_target(agent, "semantic"), unanswerable, [top_similarity]))["top_similarity"]
    print(f"  best similarity, answerable: min {min(good):.3f}, median {sorted(good)[len(good) // 2]:.3f}")
    print(f"  best similarity, unanswerable: {', '.join(f'{s:.3f}' for s in sorted(bad))}")
    for threshold in THRESHOLDS:
        kept = sum(s >= threshold for s in good)
        rejected = sum(s < threshold for s in bad)
        print(f"  cut-off {threshold:.2f}: keeps {kept}/{len(good)} answerable, rejects {rejected}/{len(bad)} unanswerable")


# --- answers --------------------------------------------------------------------------------


class _Verdict(BaseModel):
    passed: bool
    reason: str


def judge(instruction: str):
    judge_model = model(WRITER_MODEL).with_structured_output(_Verdict)

    def run(prompt: str) -> dict:
        verdict: _Verdict = judge_model.invoke(f"{instruction}\n\n{prompt}")
        return {"score": verdict.passed, "comment": verdict.reason}

    return run


_correct = judge("Decide whether the ANSWER states the same facts as the REFERENCE answer. Extra correct detail is fine; a missing or different key fact fails.")
_grounded = judge("Decide whether every factual claim in the ANSWER is supported by the RETRIEVED text. An answer that only says it does not have the information passes.")
_declined = judge("Decide whether the ANSWER says it does not have the information and does NOT go on to answer the question from general knowledge.")


def correct(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    return _correct(f"QUESTION: {inputs['question']}\nREFERENCE: {reference_outputs['answer']}\nANSWER: {outputs['answer']}")


def grounded(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    return _grounded(f"RETRIEVED:\n{outputs['retrieved'] or '(nothing)'}\n\nANSWER: {outputs['answer']}")


def declined(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    return _declined(f"QUESTION: {inputs['question']}\nANSWER: {outputs['answer']}")


async def run_answers() -> None:
    async with indexed_agent(settings.chunking_method) as agent:
        async with session_factory() as db:
            names = await retrieve.document_names(db, agent.id)
        graph = build_graph(model(AGENT_MODEL), build_kb_tools(agent.id, "hybrid", embedder=agent.embedder, store=agent.store))

        async def target(inputs: dict) -> dict:
            question = SimpleNamespace(role="user", content=inputs["question"])
            messages = build_messages("You are a helpful assistant.", None, [question], kb_instruction(names))
            state = await graph.ainvoke({"messages": messages}, config={"recursion_limit": RECURSION_LIMIT})
            retrieved = "\n\n".join(str(m.content) for m in state["messages"] if isinstance(m, ToolMessage))
            return {"answer": chunk_text(state["messages"][-1]), "retrieved": retrieved}

        scores = await experiment("answers-answerable", target, examples("answerable"), [correct, grounded])
        print(f"  answerable: correct {rate(scores['correct'])}, grounded {rate(scores['grounded'])}")
        scores = await experiment("answers-unanswerable", target, examples("unanswerable"), [declined])
        print(f"  unanswerable: declined {rate(scores['declined'])}")


COMMANDS = {"dataset": build_dataset, "chunking": run_chunking, "search": run_search, "answers": run_answers}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in COMMANDS:
        sys.exit(f"usage: python -m evals.run [{' | '.join(COMMANDS)}]")
    asyncio.run(COMMANDS[command]())
