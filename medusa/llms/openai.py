import json
import platform
import base64
import uuid
from dataclasses import dataclass, field
from typing import Literal
from collections.abc import Callable

import httpx
from openai import OpenAI
from openai.types.responses import (
    ResponseInputMessageItem,
    ResponseInputContentParam,
)
from pydantic import BaseModel

from medusa.llms.base import BaseChatLLM
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from medusa.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ImageMessage,
    SystemMessage,
    ToolCallMessage,
    ToolResultMessage,
)

# ---------------------------------------------------------------------------
# OpenAI Responses API (standard openai-responses)
# ---------------------------------------------------------------------------

@dataclass
class ChatOpenAI(BaseChatLLM):
    model: str = "gpt-5.2"
    api_key: str = ""
    provider_name: str = "openai"
    organization: str | None = None
    project: str | None = None
    base_url: str | None = None
    websocket_base_url: str | None = None
    temperature: float = 0.7
    max_retries: int = 3
    timeout: int | None = None
    default_headers: dict[str, str] | None = None
    default_query: dict[str, object] | None = None
    http_client: httpx.Client | None = None
    strict_response_validation: bool = False
    reasoning_effort: str = "medium"
    account_id: str | None = None

    # === Responses API specific ===
    _last_response_id: str | None = field(default=None, repr=False)
    _client: OpenAI | None = field(default=None, repr=False)
    _session_id: str = field(default="", repr=False)

    def __post_init__(self):
        self._client = None
        self._last_response_id = None
        self._session_id = str(uuid.uuid4())

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            headers = dict(self.default_headers) if self.default_headers else {}
            if self.account_id:
                headers["ChatGPT-Account-Id"] = self.account_id
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                max_retries=self.max_retries,
                websocket_base_url=self.websocket_base_url,
                timeout=self.timeout,
                organization=self.organization,
                project=self.project,
                default_headers=headers or None,
                default_query=self.default_query,
                http_client=self.http_client,
            )
        return self._client

    @property
    def provider(self) -> str:
        return self.provider_name

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def last_response_id(self) -> str | None:
        return self._last_response_id

    def reset_conversation(self) -> None:
        self._last_response_id = None

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }
            for t in tools
        ]

    def serialize_messages(
        self,
        messages: list[BaseMessage]
    ) -> list[ResponseInputMessageItem]:
        serialized: list[ResponseInputMessageItem] = []

        for message in messages:
            if isinstance(message, SystemMessage):
                serialized.append({
                    "role": "system",
                    "content": message.content
                })
            elif isinstance(message, ToolCallMessage):
                serialized.append({
                    "role": "assistant",
                    "content": message.content or ""
                })
            elif isinstance(message, ToolResultMessage):
                if message.image:
                    image_url = f"data:{message.mime_type};base64,{message.image_to_base64()}"
                    output: str | list[dict] = [
                        {"type": "input_text", "text": message.content},
                        {"type": "input_image", "image_url": image_url, "detail": "low"},
                    ]
                else:
                    output = message.content
                serialized.append({
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": output
                })
            elif isinstance(message, HumanMessage):
                serialized.append({
                    "role": "user",
                    "content": message.content
                })
            elif isinstance(message, AIMessage):
                serialized.append({
                    "role": "assistant",
                    "content": message.content
                })
            elif isinstance(message, ImageMessage):
                image_url = f"data:{message.mime_type};base64,{message.image_to_base64()}"
                content_parts: list[ResponseInputContentParam] = []
                if message.content:
                    content_parts.append({
                        "type": "input_text",
                        "text": message.content
                    })
                content_parts.append({
                    "type": "input_image",
                    "image_url": image_url,
                    "detail": "low"
                })
                serialized.append({
                    "role": "user",
                    "content": content_parts
                })
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")

        return serialized

    def invoke(
        self,
        messages: list[BaseMessage],
        tools: list[dict] | None = None,
        structured_output: type[BaseModel] | None = None,
        use_conversation_chain: bool = True,
        reasoning_effort: Literal["low", "medium", "high", "none"] | None = None,
    ) -> ChatLLMResponse:
        effective_effort = reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        request_params: dict = {
            "model": self.model,
            "reasoning": {"effort": effective_effort},
            "store": False,
            "prompt_cache_key": self._session_id,
        }

        if use_conversation_chain and self._last_response_id:
            request_params["previous_response_id"] = self._last_response_id
            request_params["input"] = self.serialize_messages(messages[-1:])
        else:
            request_params["input"] = self.serialize_messages(messages)

        if tools:
            request_params["tools"] = self._format_tools(tools)

        if structured_output is not None:
            request_params["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": structured_output.__name__,
                    "schema": structured_output.model_json_schema(),
                    "strict": True
                }
            }

        response = self.client.responses.create(**request_params)
        self._last_response_id = response.id

        content_value = None
        tool_calls = []

        for output_item in response.output:
            if output_item.type == "function_call":
                tool_calls.append(ToolCall(
                    id=output_item.call_id,
                    name=output_item.name,
                    arguments=json.loads(output_item.arguments) if isinstance(output_item.arguments, str) else output_item.arguments,
                    raw=str(output_item)
                ))
            elif hasattr(output_item, "content") and output_item.content:
                for content_part in output_item.content:
                    if hasattr(content_part, "text"):
                        content_value = content_part.text
                        break
            elif hasattr(output_item, "text"):
                content_value = output_item.text

        usage = self._extract_usage(response)

        return ChatLLMResponse(
            content=content_value,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )

    def _extract_usage(self, response) -> ChatLLMUsage | None:
        if not hasattr(response, "usage") or response.usage is None:
            return None
        usage = response.usage
        return ChatLLMUsage(
            prompt_tokens=getattr(usage, "input_tokens", 0),
            completion_tokens=getattr(usage, "output_tokens", 0),
            total_tokens=getattr(usage, "total_tokens", 0),
        )


# ---------------------------------------------------------------------------
# OpenAI Codex (chatgpt.com/backend-api/codex/responses) — raw SSE transport
# ---------------------------------------------------------------------------

def _decode_jwt_account_id(token: str) -> str | None:
    """Extract chatgpt_account_id from JWT payload claim."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        auth = payload.get("https://api.openai.com/auth", {})
        return auth.get("chatgpt_account_id")
    except Exception:
        return None


def _build_codex_user_agent() -> str:
    try:
        return f"pi ({platform.system().lower()} {platform.release()}; {platform.machine()})"
    except Exception:
        return "pi (browser)"


@dataclass
class ChatOpenAICodex(BaseChatLLM):
    """
    Direct SSE transport for chatgpt.com/backend-api/codex/responses.

    Mirrors @mariozechner/pi-ai openai-codex-responses provider:
    - Endpoint: {base_url}/codex/responses
    - Auth: Bearer JWT + chatgpt-account-id (extracted from JWT)
    - Headers: originator=pi, OpenAI-Beta=responses=experimental
    - System prompt: top-level `instructions` field (not inside `input`)
    - store: false (no server-side storage)
    """
    model: str = "gpt-5.4"
    api_key: str = ""
    base_url: str = "https://chatgpt.com/backend-api"
    reasoning_effort: str = "high"
    timeout: float | None = None

    def __post_init__(self):
        self._account_id: str | None = _decode_jwt_account_id(self.api_key)
        self._session_id: str = str(uuid.uuid4())

    @property
    def provider(self) -> str:
        return "openai-codex"

    @property
    def model_name(self) -> str:
        return self.model

    def _resolve_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/codex/responses"):
            return base
        if base.endswith("/codex"):
            return f"{base}/responses"
        return f"{base}/codex/responses"

    def _build_headers(self) -> dict[str, str]:
        if not self._account_id:
            raise RuntimeError(
                "Cannot extract chatgpt_account_id from Codex JWT. "
                "The token may be invalid or missing the https://api.openai.com/auth claim."
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "chatgpt-account-id": self._account_id,
            "originator": "pi",
            "User-Agent": _build_codex_user_agent(),
            "OpenAI-Beta": "responses=experimental",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }

    def _serialize_messages(
        self, messages: list[BaseMessage]
    ) -> tuple[str | None, list[dict]]:
        """Return (system_instruction, input_messages)."""
        system_instruction: str | None = None
        input_messages: list[dict] = []

        for message in messages:
            if isinstance(message, SystemMessage):
                system_instruction = message.content
            elif isinstance(message, HumanMessage):
                input_messages.append({"role": "user", "content": message.content})
            elif isinstance(message, AIMessage):
                input_messages.append({"role": "assistant", "content": message.content})
            elif isinstance(message, ToolCallMessage):
                # Codex Responses API requires an explicit function_call item in input
                # so the subsequent function_call_output can be matched by call_id.
                # 'id' must be the fc_... item ID; 'call_id' is the call_... ID.
                if message.content:
                    input_messages.append({"role": "assistant", "content": message.content})
                fc_item: dict = {
                    "type": "function_call",
                    "call_id": message.tool_call_id or "",
                    "name": message.tool_name,
                    "arguments": json.dumps(message.tool_input),
                }
                if message.tool_item_id:
                    fc_item["id"] = message.tool_item_id
                input_messages.append(fc_item)
            elif isinstance(message, ToolResultMessage):
                if message.image:
                    image_url = f"data:{message.mime_type};base64,{message.image_to_base64()}"
                    output: str | list[dict] = [
                        {"type": "input_text", "text": message.content},
                        {"type": "input_image", "image_url": image_url, "detail": "low"},
                    ]
                else:
                    output = message.content
                input_messages.append({
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": output,
                })
            elif isinstance(message, ImageMessage):
                parts: list[dict] = []
                if message.content:
                    parts.append({"type": "input_text", "text": message.content})
                image_url = f"data:{message.mime_type};base64,{message.image_to_base64()}"
                parts.append({"type": "input_image", "image_url": image_url, "detail": "low"})
                input_messages.append({"role": "user", "content": parts})
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")

        return system_instruction, input_messages

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in tools
        ]

    def _build_body(
        self,
        system_instruction: str | None,
        input_messages: list[dict],
        tools: list[dict] | None,
    ) -> dict:
        body: dict = {
            "model": self.model,
            "store": False,
            "stream": True,
            "input": input_messages,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "reasoning": {
                "effort": self.reasoning_effort,
                "summary": "auto",
            },
            "prompt_cache_key": self._session_id,
        }
        if system_instruction:
            body["instructions"] = system_instruction
        if tools:
            body["tools"] = self._format_tools(tools)
        return body

    def _do_request(
        self,
        messages: list[BaseMessage],
        tools: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ChatLLMResponse:
        """Shared SSE request logic for invoke/invoke_stream."""
        system_instruction, input_messages = self._serialize_messages(messages)
        body = self._build_body(system_instruction, input_messages, tools)
        headers = self._build_headers()
        url = self._resolve_url()
        with httpx.Client(timeout=self.timeout or 120.0) as client:
            with client.stream("POST", url, headers=headers, content=json.dumps(body)) as response:
                if not response.is_success:
                    raw = response.read().decode(errors="replace")
                    raise RuntimeError(
                        f"Codex API error {response.status_code}: {raw[:500]}"
                    )
                return self._parse_sse_response(response, on_delta=on_delta)

    def invoke(
        self,
        messages: list[BaseMessage],
        tools: list[dict] | None = None,
        structured_output: type[BaseModel] | None = None,
    ) -> ChatLLMResponse:
        """Blocking SSE request to chatgpt.com/backend-api/codex/responses."""
        return self._do_request(messages, tools)

    def invoke_stream(
        self,
        messages: list[BaseMessage],
        tools: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> ChatLLMResponse:
        """Like invoke() but streams text deltas via on_delta callback as they arrive."""
        return self._do_request(messages, tools, on_delta=on_delta)

    def _parse_sse_response(self, response: httpx.Response, on_delta: Callable[[str], None] | None = None) -> ChatLLMResponse:
        """Parse streaming SSE response into ChatLLMResponse."""
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage: ChatLLMUsage | None = None

        # Accumulate pending tool call arguments by call_id
        pending_tool_calls: dict[str, dict] = {}  # call_id -> {name, args_str}

        buffer = ""
        for raw_chunk in response.iter_bytes():
            buffer += raw_chunk.decode(errors="replace")
            while "\n\n" in buffer:
                idx = buffer.index("\n\n")
                chunk = buffer[:idx]
                buffer = buffer[idx + 2:]

                data_lines = [
                    line[5:].strip()
                    for line in chunk.split("\n")
                    if line.startswith("data:")
                ]
                data_str = "\n".join(data_lines).strip()
                if not data_str or data_str == "[DONE]":
                    continue

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type == "response.output_item.added":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        item_id = item.get("id", "")
                        pending_tool_calls[item_id] = {
                            "name": item.get("name", ""),
                            "call_id": item.get("call_id") or item_id,
                            "args_str": "",
                        }

                elif event_type == "response.function_call_arguments.delta":
                    item_id = event.get("item_id", "") or event.get("call_id", "")
                    delta = event.get("delta", "")
                    if item_id in pending_tool_calls:
                        pending_tool_calls[item_id]["args_str"] += delta

                elif event_type == "response.function_call_arguments.done":
                    item_id = event.get("item_id", "") or event.get("call_id", "")
                    if item_id in pending_tool_calls:
                        pending = pending_tool_calls.pop(item_id)
                        args_str = event.get("arguments", pending["args_str"])
                        try:
                            args = json.loads(args_str) if args_str else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(
                            id=pending["call_id"],
                            item_id=item_id,
                            name=pending["name"],
                            arguments=args,
                            raw=args_str,
                        ))

                elif event_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        content_parts.append(delta)
                        if on_delta:
                            on_delta(delta)

                elif event_type in ("response.completed", "response.done"):
                    resp = event.get("response", {})
                    u = resp.get("usage", {})
                    if u:
                        usage = ChatLLMUsage(
                            prompt_tokens=u.get("input_tokens", 0),
                            completion_tokens=u.get("output_tokens", 0),
                            total_tokens=u.get("total_tokens", 0),
                        )

                elif event_type == "error":
                    code = event.get("code", "")
                    msg = event.get("message", "")
                    raise RuntimeError(f"Codex error: {msg or code or str(event)}")

                elif event_type == "response.failed":
                    msg = event.get("response", {}).get("error", {}).get("message", "")
                    raise RuntimeError(f"Codex response failed: {msg}")

        content = "".join(content_parts) or None
        return ChatLLMResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
        )
