"""Splits a document's pages into chunks. Two methods; the LangSmith comparison picks the default.

- recursive: chunks of about 1,000 characters, overlapping. The same chunk is searched and
  given to the model.
- parent_child: small chunks are searched, and the model is given the larger section each
  one belongs to. More precise matching with more context, at the cost of longer model input.
"""
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

RECURSIVE_SIZE, RECURSIVE_OVERLAP = 1000, 150
PARENT_SIZE = 2000
CHILD_SIZE, CHILD_OVERLAP = 400, 50

METHODS = ("recursive", "parent_child")


@dataclass(frozen=True)
class Chunk:
    content: str  # the text that is searched (embedded and keyword-matched)
    context: str | None  # what the model is given instead, when it differs
    page: int | None


def _header(document_name: str, page: int | None) -> str:
    """Put at the top of every chunk, so a chunk still says where it came from on its own."""
    return f"[{document_name}, page {page}]\n" if page is not None else f"[{document_name}]\n"


def split(pages: list[tuple[int | None, str]], method: str, document_name: str) -> list[Chunk]:
    if method not in METHODS:
        raise ValueError(f"unknown chunking method: {method}")
    recursive = RecursiveCharacterTextSplitter(chunk_size=RECURSIVE_SIZE, chunk_overlap=RECURSIVE_OVERLAP)
    parents = RecursiveCharacterTextSplitter(chunk_size=PARENT_SIZE, chunk_overlap=0)
    children = RecursiveCharacterTextSplitter(chunk_size=CHILD_SIZE, chunk_overlap=CHILD_OVERLAP)

    chunks: list[Chunk] = []
    for page, text in pages:
        if not text.strip():
            continue
        header = _header(document_name, page)
        if method == "recursive":
            chunks += [Chunk(header + piece, None, page) for piece in recursive.split_text(text)]
        else:
            for parent in parents.split_text(text):
                chunks += [Chunk(header + child, header + parent, page) for child in children.split_text(parent)]
    return chunks
