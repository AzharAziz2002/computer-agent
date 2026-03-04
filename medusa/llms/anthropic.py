from anthropic.types import Message,MessageParam,ImageBlockParam,Base64ImageSourceParam,TextBlockParam,CacheControlEphemeralParam,ThinkingConfigDisabledParam,ThinkingConfigEnabledParam,ToolUseBlockParam,ToolResultBlockParam
from medusa.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ImageMessage, ToolCallMessage, ToolResultMessage
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from medusa.llms.base import BaseChatLLM
from dataclasses import dataclass
from anthropic import Anthropic
from pydantic import BaseModel
from httpx import Client
import json

@dataclass
class ChatAnthropic(BaseChatLLM):
    def __init__(self, model: str, api_key: str, thinking_budget:int=-1, temperature: float = 0.7, max_tokens: int = 8192, auth_token: str | None = None, base_url: str | None = None, timeout: float | None = None, max_retries: int = 3, default_headers: dict[str, str] | None = None, default_query: dict[str, object] | None = None, http_client: Client | None = None, strict_response_validation: bool = False):
        self.model = model
        self.api_key = api_key
        self.auth_token = auth_token
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.base_url = base_url
        self.thinking_budget=thinking_budget
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = default_headers
        self.default_query = default_query
        self.http_client = http_client
        self.strict_response_validation = strict_response_validation
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = Anthropic(**{
                "api_key": self.api_key,
                "auth_token": self.auth_token,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "default_headers": self.default_headers,
                "default_query": self.default_query,
                "http_client": self.http_client,
            })
        return self._client

    @property
    def provider(self):
        return "anthropic"

    @property
    def model_name(self):
        return self.model

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert generic tool schemas to Anthropic format."""
        formatted = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"]
            }
            for t in tools
        ]
        if formatted:
            formatted[-1]["cache_control"] = {"type": "ephemeral"}
        return formatted

    def serialize_messages(self, messages: list[BaseMessage]):
        """Serialize messages to Anthropic format."""
        system_instruction = None
        serialized = []
        i = 0
        while i < len(messages):
            message = messages[i]
            if isinstance(message, SystemMessage):
                system_instruction = message.content
                i += 1
            elif isinstance(message, ToolCallMessage):
                # Collect all interleaved ToolCall+ToolResult pairs for this turn
                # into a single assistant message + single user message.
                tool_calls: list[ToolCallMessage] = []
                tool_results: list[ToolResultMessage] = []
                j = i
                while j < len(messages) and isinstance(messages[j], (ToolCallMessage, ToolResultMessage)):
                    if isinstance(messages[j], ToolCallMessage):
                        tool_calls.append(messages[j])
                    else:
                        tool_results.append(messages[j])
                    j += 1

                # Single assistant message with all tool_use blocks
                content = []
                if tool_calls[0].content:
                    content.append(TextBlockParam(type="text", text=tool_calls[0].content))
                for tc in tool_calls:
                    content.append(ToolUseBlockParam(
                        type="tool_use",
                        id=tc.tool_call_id,
                        name=tc.tool_name,
                        input=tc.tool_input
                    ))
                serialized.append(MessageParam(role="assistant", content=content))

                # Single user message with all tool_result blocks
                result_blocks = []
                for tr in tool_results:
                    result_content = [{"type": "text", "text": tr.content}]
                    if tr.image:
                        tr.scale_image(scale=0.7)
                        result_content.append({
                            "type": "image",
                            "source": {"type": "base64", "data": tr.image_to_base64(), "media_type": tr.mime_type}
                        })
                    result_blocks.append(ToolResultBlockParam(
                        type="tool_result",
                        tool_use_id=tr.tool_call_id,
                        content=result_content
                    ))
                if result_blocks:
                    serialized.append(MessageParam(role="user", content=result_blocks))

                i = j
            elif isinstance(message, HumanMessage):
                content = [TextBlockParam(type="text", text=message.content)]
                serialized.append(MessageParam(role="user", content=content))
                i += 1
            elif isinstance(message, AIMessage):
                content = [TextBlockParam(type="text", text=message.content)]
                serialized.append(MessageParam(role="assistant", content=content))
                i += 1
            elif isinstance(message, ImageMessage):
                message.scale_image(scale=0.7)
                content = [
                    TextBlockParam(type="text", text=message.content),
                    ImageBlockParam(type="image", source=Base64ImageSourceParam(
                        type="base64", data=message.image_to_base64(), media_type=message.mime_type
                    ))
                ]
                serialized.append(MessageParam(role="user", content=content))
                i += 1
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")
        return system_instruction, serialized

    def _apply_cache_control(self, messages: list, cache_query: bool = True):
        """Apply ephemeral cache breakpoints to stable content."""
        # Cache the user query (first user message)
        if cache_query:
            for msg in messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                    block = msg["content"][0]
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["cache_control"] = {"type": "ephemeral"}
                        break

        # Cache the second-to-last screenshot tool_result
        screenshot_results = []
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content", [])
                        has_screenshot = any(
                            isinstance(c, dict) and (
                                c.get("type") == "image"
                                or (c.get("type") == "text" and c.get("text", "").startswith("<desktop_state>"))
                            )
                            for c in (content if isinstance(content, list) else [])
                        )
                        if has_screenshot:
                            screenshot_results.append(block)

        if len(screenshot_results) >= 2:
            screenshot_results[-2]["cache_control"] = {"type": "ephemeral"}

    def invoke(self, messages: list[BaseMessage], tools: list[dict]|None=None, structured_output:BaseModel|None = None):
        """Invoke Anthropic API with optional native tool calling."""
        system_instruction, messages = self.serialize_messages(messages)
        self._apply_cache_control(messages)
        thinking_enabled = self.thinking_budget > -1
        params = dict(
            max_tokens=self.max_tokens,
            model=self.model,
            thinking=ThinkingConfigEnabledParam(type="enabled",budget_tokens=self.thinking_budget) if thinking_enabled else ThinkingConfigDisabledParam(type="disabled"),
            system=[TextBlockParam(type="text",text=system_instruction,cache_control=CacheControlEphemeralParam(type="ephemeral",ttl='5m'))],
            messages=messages,
        )
        if not thinking_enabled:
            params["temperature"] = self.temperature
        if tools:
            params["tools"] = self._format_tools(tools)
            params["tool_choice"] = {"type": "any"}
        completion = self.client.messages.create(**params)
        if not isinstance(completion,Message):
            raise ValueError("Unexpected response type from Anthropic API")
        thinking_content,text_content=[],[]
        tool_calls = []
        for block in completion.content:
            match block.type:
                case "text":
                    text_content.append(block.text)
                case "thinking":
                    thinking_content.append(block.thinking)
                case "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else json.loads(block.input),
                        raw=str(block)
                    ))
                case _:
                    pass
        content="\n".join(text_content)
        thinking="\n".join(thinking_content)
        return ChatLLMResponse(
            thinking=thinking,
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=ChatLLMUsage(
                prompt_tokens=completion.usage.input_tokens,
                completion_tokens=completion.usage.output_tokens,
                total_tokens=completion.usage.input_tokens+completion.usage.output_tokens
            )
        )
