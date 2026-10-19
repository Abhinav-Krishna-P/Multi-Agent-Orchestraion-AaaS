"""In-memory stand-ins for Gemini embeddings and Chroma, plus a tiny PDF builder."""
import hashlib
import math
import re

from app.rag.vector_store import VectorStoreUnavailable

DIMENSIONS = 2048  # large enough that unrelated words almost never collide


class FakeEmbedder:
    """Turns text into a bag-of-words vector, so texts that share words are closer."""

    model = "fake-embedding"

    def __init__(self):
        self.calls: list[list[str]] = []
        self.error: Exception | None = None
        self.before_return = None  # optional async hook, run after "embedding" finishes

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for word in re.findall(r"\w+", text.lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.error:
            raise self.error
        self.calls.append(list(texts))
        if self.before_return:
            await self.before_return()
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.error:
            raise self.error
        return self._vector(text)


class FakeVectorStore:
    def __init__(self):
        self.items: dict[str, tuple[list[float], dict]] = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise VectorStoreUnavailable()

    async def add(self, ids, vectors, metadatas):
        self._check()
        for id_, vector, metadata in zip(ids, vectors, metadatas, strict=True):
            self.items[id_] = (vector, metadata)

    async def query(self, vector, agent_id, k, filters=None):
        self._check()
        wanted = {"agent_id": str(agent_id), **(filters or {})}
        scored = [
            (id_, sum(a * b for a, b in zip(vector, stored)))
            for id_, (stored, metadata) in self.items.items()
            if all(metadata.get(key) == value for key, value in wanted.items())
        ]
        return sorted(scored, key=lambda pair: pair[1], reverse=True)[:k]

    async def delete_document(self, document_id):
        self._check()
        self.items = {i: v for i, v in self.items.items() if v[1]["document_id"] != str(document_id)}

    async def delete_agent(self, agent_id):
        self._check()
        self.items = {i: v for i, v in self.items.items() if v[1]["agent_id"] != str(agent_id)}


def make_pdf(pages: list[str]) -> bytes:
    """A minimal text PDF with one line of text per page ("" makes a page with no text)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = "<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode() if text else b""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources {font} "
            f"/Contents {4 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
