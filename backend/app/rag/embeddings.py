"""Text embeddings. Gemini on the platform's own key; tests swap in a stand-in."""
import asyncio
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Protocol

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import get_settings
from app.rag.extract import DocumentError

BATCH_SIZE = 100
RETRY_WAITS = (2, 4, 8, 16, 32)  # seconds
BUSY = "The embedding service is busy. Delete this document and try again later."


class Embedder(Protocol):
    model: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def _is_rate_limit(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}"
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "ResourceExhausted" in text


async def with_rate_limit_retries(call: Callable[[], Awaitable], *, sleep=asyncio.sleep):
    """Runs `call`, waiting and trying again when the provider says it is rate-limited."""
    for wait in RETRY_WAITS:
        try:
            return await call()
        except Exception as error:
            if not _is_rate_limit(error):
                raise
            await sleep(wait)
    try:
        return await call()
    except Exception as error:
        if _is_rate_limit(error):
            raise DocumentError(BUSY) from error
        raise


class GeminiEmbedder:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self._api_key = api_key
        self._client: GoogleGenerativeAIEmbeddings | None = None

    def _get_client(self) -> GoogleGenerativeAIEmbeddings:
        # Built on first use: every chat asks for the embedder, but only agents with a
        # knowledge base use it, and the client refuses to exist without a key.
        if self._client is None:
            self._client = GoogleGenerativeAIEmbeddings(model=f"models/{self.model}", google_api_key=self._api_key)
        return self._client

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors += await with_rate_limit_retries(lambda batch=batch: client.aembed_documents(batch))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        client = self._get_client()
        return await with_rate_limit_retries(lambda: client.aembed_query(text))


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    return GeminiEmbedder(settings.embedding_model, settings.platform_gemini_api_key or "")
