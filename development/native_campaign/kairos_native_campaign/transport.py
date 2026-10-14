"""Finite Responses-API-shaped transport with no network or credentials.

The actual LLMGateway parses replies and accounts prices. The tokens, replies
and request identifiers here are explicitly synthetic engineering fixtures.
There is no live-client fallback, endpoint, callback, secret, retry or I/O.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True, slots=True)
class NoNetworkReply:
    schema_name: str
    model: str
    output_json: str
    input_tokens: int = 150
    output_tokens: int = 30

    def __post_init__(self):
        if not self.model or not self.schema_name or len(self.output_json.encode("utf-8")) > 65_536:
            raise ValueError("bounded explicit engineering response required")
        if any(
            type(value) is not int or not 0 <= value <= 8_192
            for value in (self.input_tokens, self.output_tokens)
        ):
            raise ValueError("engineering token usage must be bounded nonnegative integers")


class NoNetworkResponsesTransport:
    def __init__(self, replies: tuple[NoNetworkReply, ...]):
        if (
            type(replies) is not tuple
            or len(replies) > 32
            or any(type(x) is not NoNetworkReply for x in replies)
        ):
            raise ValueError("finite exact no-network response program required")
        self._replies = deque(replies)
        self.calls: list[dict] = []
        self.responses = self

    async def parse(self, **request):
        self.calls.append(request)
        if not self._replies:
            raise RuntimeError("ENGINEERING_RESPONSE_PROGRAM_EXHAUSTED_NO_RETRY")
        reply = self._replies.popleft()
        schema = request["text_format"]
        if request["model"] != reply.model or schema.__name__ != reply.schema_name:
            raise RuntimeError("ENGINEERING_RESPONSE_ROUTE_OR_SCHEMA_MISMATCH")
        return SimpleNamespace(
            status="completed",
            model=reply.model,
            id=f"fixture-no-network-{len(self.calls)}",
            output_parsed=schema.model_validate_json(reply.output_json),
            output_text=reply.output_json,
            usage=SimpleNamespace(input_tokens=reply.input_tokens, output_tokens=reply.output_tokens),
        )
