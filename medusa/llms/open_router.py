from openai.types.chat import ChatCompletionAssistantMessageParam,ChatCompletionUserMessageParam,ChatCompletionContentPartTextParam,ChatCompletionContentPartImageParam,ChatCompletionSystemMessageParam,ChatCompletionToolMessageParam
from openai.types.shared_params.response_format_json_schema import JSONSchema, ResponseFormatJSONSchema
from medusa.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ImageMessage, ToolCallMessage, ToolResultMessage
from openai.types.chat.chat_completion_content_part_image_param import ImageURL
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from medusa.llms.base import BaseChatLLM
from dataclasses import dataclass
from pydantic import BaseModel
from openai import OpenAI
from httpx import Client
import json

@dataclass
class ChatOpenRouter(BaseChatLLM):
    def __init__(self, model: str, api_key: str, base_url: str|None=None, temperature: float = 0.7,max_retries: int = 3,timeout: int|None=None, default_headers: dict[str, str] | None = None, default_query: dict[str, object] | None = None, http_client: Client | None = None, strict_response_validation: bool = False):
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_url = base_url
        self.timeout = timeout
        self.default_headers = default_headers
        self.default_query = default_query
        self.http_client = http_client
        self.strict_response_validation = strict_response_validation

    @property
    def client(self):
        return OpenAI(**{
            "api_key": self.api_key,
            "base_url": self.base_url or 'https://openrouter.ai/api/v1',
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
            "http_client": self.http_client,
        })

    @property
    def provider(self):
        return "openrouter"

    @property
    def model_name(self):
        return self.model

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert generic tool schemas to OpenAI Chat Completions format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
            }
            for t in tools
        ]

    def serialize_messages(self, messages: list[BaseMessage]):
        """Serialize messages to OpenRouter format."""
        serialized = []
        for message in messages:
            if isinstance(message, SystemMessage):
                content=[ChatCompletionContentPartTextParam(type="text",text=message.content)]
                serialized.append(ChatCompletionSystemMessageParam(role="system",content=content))
            elif isinstance(message, ToolCallMessage):
                serialized.append(ChatCompletionAssistantMessageParam(
                    role="assistant",
                    content=message.content or None,
                    tool_calls=[{
                        "id": message.tool_call_id,
                        "type": "function",
                        "function": {"name": message.tool_name, "arguments": json.dumps(message.tool_input)}
                    }]
                ))
            elif isinstance(message, ToolResultMessage):
                serialized.append(ChatCompletionToolMessageParam(
                    role="tool",
                    tool_call_id=message.tool_call_id,
                    content=message.content
                ))
            elif isinstance(message, HumanMessage):
                content=[ChatCompletionContentPartTextParam(type="text",text=message.content)]
                serialized.append(ChatCompletionUserMessageParam(role="user",content=content))
            elif isinstance(message, AIMessage):
                content=[ChatCompletionContentPartTextParam(type="text",text=message.content)]
                serialized.append(ChatCompletionAssistantMessageParam(role="assistant",content=content))
            elif isinstance(message, ImageMessage):
                message.scale_image(scale=0.7)
                image=f"data:{message.mime_type};base64,{message.image_to_base64()}"
                content=[
                    ChatCompletionContentPartTextParam(type="text",text=message.content),
                    ChatCompletionContentPartImageParam(type="image_url",image_url=ImageURL(url=image,detail="auto"))
                ]
                serialized.append(ChatCompletionUserMessageParam(role="user",content=content))
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")
        return serialized

    def invoke(self, messages: list[BaseMessage], tools: list[dict]|None=None, structured_output:BaseModel|None=None) -> ChatLLMResponse:
        """Invoke OpenRouter API with optional native tool calling."""
        params = dict(
            model=self.model,
            messages=self.serialize_messages(messages),
            temperature=self.temperature,
        )
        if tools:
            params["tools"] = self._format_tools(tools)
        if structured_output:
            params["response_format"] = ResponseFormatJSONSchema(
                type="json_schema",
                json_schema=JSONSchema(
                    name=structured_output.__class__.__name__,
                    description="Model output structured as JSON schema",
                    schema=structured_output.model_json_schema()
                )
            )
        completion=self.client.chat.completions.create(**params)
        msg = completion.choices[0].message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments,
                    raw=str(tc)
                ))
        content=msg.content
        if structured_output and content:
            content = structured_output.model_validate_json(content)
        return ChatLLMResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=ChatLLMUsage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens
            )
        )
