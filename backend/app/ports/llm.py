from collections.abc import AsyncIterator
from typing import Protocol

from app.domain.llm import LLMEvent, LLMRequest


class LLM(Protocol):
    """Asíncrono: el chat hace streaming por SSE y debe poder cancelarse [F7]."""

    model: str

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Emite TextDelta y, al final, Usage.

        Raises: LLMTimeoutError, LLMRateLimitError, LLMUnavailableError.
        """
        ...
