"""Stand-in chat models, so tests never call a real provider."""
import asyncio
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


def _chunk(content: Any, index: int, call_number: int) -> AIMessageChunk:
    """A text chunk, or a tool call written as {"tool": name, "args": {...}}."""
    if isinstance(content, dict) and "tool" in content:
        return AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": content["tool"],
                    "args": json.dumps(content["args"]),
                    "id": f"call_{call_number}_{index}",
                    "index": index,  # calls in one reply stay separate
                }
            ],
        )
    return AIMessageChunk(content=content)


class ScriptedChatModel(BaseChatModel):
    """Plays back scripted replies, one per call. A reply is a list of chunks; each chunk is
    text or a tool call. Can fail partway, or wait at a gate before each later chunk."""

    replies: list[list[Any]]
    fail_after: int | None = None
    gate: Any = None
    received: list[list[Any]] = []
    bound: list[str] | None = None  # names of the tools the model was given, if any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound = [tool.name for tool in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        chunks = self.replies.pop(0)
        self.received.append(list(messages))
        if self.fail_after is not None:
            raise RuntimeError("provider exploded with secret detail sk-leaky")
        text = "".join(c for c in chunks if isinstance(c, str))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.replies:
            raise RuntimeError("the scripted model ran out of replies")
        chunks = self.replies.pop(0)
        self.received.append(list(messages))
        call_number = len(self.received)
        for index, content in enumerate(chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("provider exploded with secret detail sk-leaky")
            if index > 0 and self.gate is not None:
                await self.gate.wait()
            chunk = ChatGenerationChunk(message=_chunk(content, index, call_number))
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk
            await asyncio.sleep(0)


def scripted(*replies: Any, **kwargs) -> ScriptedChatModel:
    """Each reply is a list of chunks, or a single tool call dict (shorthand for a one-chunk reply)."""
    normalised = [[reply] if isinstance(reply, dict) else list(reply) for reply in replies]
    return ScriptedChatModel(replies=normalised, received=[], **kwargs)
