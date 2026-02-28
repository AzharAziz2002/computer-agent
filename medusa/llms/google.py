from medusa.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ImageMessage, ToolCallMessage, ToolResultMessage
from google.genai.types import Part, Content, GenerateContentConfigDict, Modality, ThinkingConfig, FunctionDeclaration, Tool as GoogleTool
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from google.genai.client import Client, DebugConfig
from google.auth.credentials import Credentials
from medusa.llms.base import BaseChatLLM
from dataclasses import dataclass
from google.genai import types
from pydantic import BaseModel
import asyncio

def run_async(coro):
    """Run an async coroutine in both Jupyter notebooks and normal Python scripts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.get_event_loop().run_until_complete(coro)
    else:
        return asyncio.run(coro)

@dataclass
class ChatGoogle(BaseChatLLM):
    def __init__(self, model: str, thinking_budget: int=-1, api_key: str=None, vertexai: bool|None=None, project: str|None=None, location: str|None=None, credentials: Credentials|None=None, http_options: types.HttpOptions | types.HttpOptionsDict | None = None, debug_config: DebugConfig | None = None, temperature: float = 0.7):
        self.model = model
        self.api_key = api_key
        self.vertexai = vertexai
        self.temperature = temperature
        self.credentials = credentials
        self.project = project
        self.location = location
        self.http_options = http_options
        self.debug_config = debug_config
        self.thinking_budget = thinking_budget
        self._client = None

    @property
    def provider(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(**{
                "api_key": self.api_key,
                "vertexai": self.vertexai,
                "project": self.project,
                "location": self.location,
                "credentials": self.credentials,
                "http_options": self.http_options,
                "debug_config": self.debug_config
            })
        return self._client

    @staticmethod
    def _sanitize_schema(schema: dict) -> dict:
        """Recursively sanitize JSON schema for Google FunctionDeclaration compatibility.

        Fixes: prefixItems (tuple types) → simple array, non-string enums → type only.
        """
        if not isinstance(schema, dict):
            return schema
        result = {}
        for key, value in schema.items():
            if key == 'prefixItems':
                # Tuple types unsupported — convert to simple typed array
                item_type = value[0].get('type', 'integer') if value and isinstance(value[0], dict) else 'integer'
                result.setdefault('type', 'array')
                result.setdefault('items', {'type': item_type})
            elif key == 'enum' and isinstance(value, list):
                if all(isinstance(v, str) for v in value):
                    result[key] = value  # Keep string enums as-is
                else:
                    # Integer/number enums unsupported — replace with plain type
                    result.setdefault('type', 'integer' if all(isinstance(v, int) for v in value) else 'number')
            elif key == 'properties' and isinstance(value, dict):
                result[key] = {k: ChatGoogle._sanitize_schema(v) for k, v in value.items()}
            elif key in ('anyOf', 'oneOf', 'allOf') and isinstance(value, list):
                result[key] = [ChatGoogle._sanitize_schema(v) for v in value]
            elif key == 'items' and isinstance(value, dict):
                result[key] = ChatGoogle._sanitize_schema(value)
            else:
                result[key] = value
        return result

    def _format_tools(self, tools: list[dict]) -> list:
        """Convert generic tool schemas to Google format."""
        declarations = []
        for t in tools:
            declarations.append(FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=self._sanitize_schema(t["parameters"])
            ))
        return [GoogleTool(function_declarations=declarations)]

    def serialize_messages(self, messages: list[BaseMessage]) -> tuple[str|None, list[Content]]:
        """Serialize messages to Google format."""
        serialized = []
        system_instruction = None
        for message in messages:
            if isinstance(message, SystemMessage):
                system_instruction = message.content
            elif isinstance(message, ToolCallMessage):
                serialized.append(Content(role="model", parts=[
                    Part.from_function_call(name=message.tool_name, args=message.tool_input)
                ]))
            elif isinstance(message, ToolResultMessage):
                serialized.append(Content(role="user", parts=[
                    Part.from_function_response(name=message.tool_name, response={"result": message.content})
                ]))
            elif isinstance(message, HumanMessage):
                serialized.append(Content(role="user", parts=[Part(text=message.content)]))
            elif isinstance(message, AIMessage):
                serialized.append(Content(role="model", parts=[Part(text=message.content)]))
            elif isinstance(message, ImageMessage):
                message.scale_image(scale=0.7)
                data = message.image_to_bytes()
                serialized.append(
                    Content(role="user", parts=[
                        Part(text=message.content),
                        Part.from_bytes(data=data, mime_type=message.mime_type)
                    ])
                )
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")
        return system_instruction, serialized

    def invoke(self, messages: list[BaseMessage], tools: list[dict]|None=None, structured_output: BaseModel | None = None) -> ChatLLMResponse:
        """Invoke Google Generative AI with optional native tool calling."""
        system_instruction, contents = self.serialize_messages(messages)
        config: GenerateContentConfigDict = {
            "temperature": self.temperature,
            "system_instruction": system_instruction,
            "response_modalities": [Modality.TEXT],
            "thinking_config": ThinkingConfig(thinking_budget=self.thinking_budget, include_thoughts=True)
        }
        if tools:
            config["tools"] = self._format_tools(tools)
        if structured_output:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = structured_output.model_json_schema()
        completion = self.client.models.generate_content(
            model=self.model,
            config=config,
            contents=contents
        )
        if structured_output:
            content = structured_output.model_validate(completion.parsed)
            return ChatLLMResponse(content=content, usage=self._extract_usage(completion))

        thinking_parts, text_parts = [], []
        tool_calls = []
        for part in completion.candidates[0].content.parts:
            if part.thought:
                thinking_parts.append(part.text)
            elif part.function_call:
                tool_calls.append(ToolCall(
                    name=part.function_call.name,
                    arguments=dict(part.function_call.args) if part.function_call.args else {},
                    raw=str(part.function_call)
                ))
            else:
                text_parts.append(part.text)
        content = "".join(text_parts)
        thinking = "".join(thinking_parts) if thinking_parts else None
        return ChatLLMResponse(
            thinking=thinking,
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=self._extract_usage(completion),
        )

    def _extract_usage(self, completion) -> ChatLLMUsage:
        return ChatLLMUsage(
            prompt_tokens=completion.usage_metadata.prompt_token_count or 0,
            completion_tokens=completion.usage_metadata.candidates_token_count or 0,
            total_tokens=completion.usage_metadata.total_token_count or 0
        )
