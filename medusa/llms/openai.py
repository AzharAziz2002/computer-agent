from openai import OpenAI
from openai.types.responses import (
    ResponseInputMessageItem,
    ResponseInputContentParam,
)
from medusa.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ImageMessage, ToolCallMessage, ToolResultMessage
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from medusa.llms.base import BaseChatLLM
from dataclasses import dataclass, field
from pydantic import BaseModel
from httpx import Client
from typing import Literal
import json

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
    http_client: Client | None = None
    strict_response_validation: bool = False
    reasoning_effort: str = "medium"
    account_id: str | None = None

    # === Responses API specific ===
    _last_response_id: str | None = field(default=None, repr=False)
    _client: OpenAI | None = field(default=None, repr=False)

    def __post_init__(self):
        self._client = None
        self._last_response_id = None

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
        """ID of last response for continuing chain."""
        return self._last_response_id

    def reset_conversation(self) -> None:
        """Reset conversation chain."""
        self._last_response_id = None

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert generic tool schemas to OpenAI Responses API format."""
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
        """Serialize messages to OpenAI Responses API format."""
        serialized: list[ResponseInputMessageItem] = []

        for message in messages:
            if isinstance(message, SystemMessage):
                serialized.append({
                    "role": "system",
                    "content": message.content
                })
            elif isinstance(message, ToolCallMessage):
                # In Responses API, function calls are output items
                # We store them as the assistant's response for history
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
        tools: list[dict]|None = None,
        structured_output: type[BaseModel] | None = None,
        use_conversation_chain: bool = True,
        reasoning_effort: Literal["low", "medium", "high", "none"] | None = None,
    ) -> ChatLLMResponse:
        """Invoke OpenAI Responses API with optional native tool calling."""
        effective_effort = reasoning_effort if reasoning_effort is not None else self.reasoning_effort
        request_params: dict = {
            "model": self.model,
            "reasoning": {"effort": effective_effort},
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
        """Extract token usage information."""
        if not hasattr(response, "usage") or response.usage is None:
            return None
        usage = response.usage
        return ChatLLMUsage(
            prompt_tokens=getattr(usage, "input_tokens", 0),
            completion_tokens=getattr(usage, "output_tokens", 0),
            total_tokens=getattr(usage, "total_tokens", 0),
        )
