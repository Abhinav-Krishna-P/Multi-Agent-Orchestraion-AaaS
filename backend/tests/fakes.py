"""Stand-in chat models, so tests never call a real provider."""
import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Streams the given chunks. Can fail partway, or wait at a gate before each later chunk."""

    replies: list[list[Any]]
    fail_after: int | None = None
    gate: Any = None
    received: list[list[Any]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        chunks = self.replies.pop(0)
        self.received.append(list(messages))
        if self.fail_after is not None:
            raise RuntimeError("provider exploded with secret detail sk-leaky")
        text = "".join(c for c in chunks if isinstance(c, str))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        chunks = self.replies.pop(0)
        self.received.append(list(messages))
        for index, content in enumerate(chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("provider exploded with secret detail sk-leaky")
            if index > 0 and self.gate is not None:
                await self.gate.wait()
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=content))
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk
            await asyncio.sleep(0)


def scripted(*replies: list[Any], **kwargs) -> ScriptedChatModel:
    return ScriptedChatModel(replies=[list(r) for r in replies], received=[], **kwargs)
