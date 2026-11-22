"""Turns an uploaded file or pasted text into pages of plain text."""
import io

from pypdf import PdfReader

MAX_PDF_PAGES = 300


class DocumentError(Exception):
    """A problem with a document that its owner can act on. The message is shown to them."""


def _pdf_pages(data: bytes) -> list[tuple[int | None, str]]:
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception as exc:  # not a PDF, damaged, or password-protected
        raise DocumentError("This PDF couldn't be opened.") from exc
    if page_count > MAX_PDF_PAGES:
        raise DocumentError("This PDF has more than 300 pages.")
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""  # one unreadable page should not sink the whole document
        if text:
            pages.append((number, text))
    if not pages:
        # Scanned or image-only: there is no OCR in the MVP.
        raise DocumentError("This PDF has no readable text.")
    return pages


def extract_pages(source_type: str, data: bytes) -> list[tuple[int | None, str]]:
    """Returns (page number, text) pairs. Only PDFs have page numbers; pages with no text are left out."""
    if source_type == "pdf":
        return _pdf_pages(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentError("This file isn't readable text.") from exc
    if "\x00" in text:
        raise DocumentError("This file isn't readable text.")
    if not text.strip():
        raise DocumentError("This file is empty.")
    return [(None, text.strip())]
