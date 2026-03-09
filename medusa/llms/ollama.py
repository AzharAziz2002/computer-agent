from medusa.messages import BaseMessage, SystemMessage, AIMessage, HumanMessage, ImageMessage, ToolCallMessage, ToolResultMessage
from medusa.llms.views import ChatLLMResponse, ChatLLMUsage, ToolCall
from medusa.llms.base import BaseChatLLM
from ollama import Client,Image,Message
from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class ChatOllama(BaseChatLLM):
    def __init__(self,host: str|None=None, model: str|None=None, think:bool=False, temperature: float = 0.7,timeout: int|None=None):
        self.host = host
        self.model = model
        self.think=think
        self.temperature = temperature
        self.timeout = timeout
        self._client = None

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = Client(host=self.host,timeout=self.timeout)
        return self._client

    @property
    def model_name(self) -> str:
        return self.model

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert generic tool schemas to Ollama format."""
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

    def serialize_messages(self, messages: list[BaseMessage]) -> list[dict]:
        """Serialize messages to Ollama format."""
        serialized = []
        for message in messages:
            if isinstance(message, SystemMessage):
                serialized.append(Message(role="system", content=message.content))
            elif isinstance(message, ToolCallMessage):
                serialized.append(Message(
                    role="assistant",
                    content=message.content or "",
                    tool_calls=[Message.ToolCall(
                        function=Message.ToolCall.Function(
                            name=message.tool_name,
                            arguments=message.tool_input
                        )
                    )]
                ))
            elif isinstance(message, ToolResultMessage):
                if message.image:
                    from io import BytesIO
                    buf = BytesIO()
                    fmt = message.mime_type.split("/")[-1]
                    message.image.save(buf, format=fmt, quality=80)
                    serialized.append(Message(role="tool", content=message.content, images=[Image(value=buf.getvalue())]))
                else:
                    serialized.append(Message(role="tool", content=message.content))
            elif isinstance(message, HumanMessage):
                serialized.append(Message(role="user", content=message.content))
            elif isinstance(message, AIMessage):
                serialized.append(Message(role="assistant", content=message.content))
            elif isinstance(message, ImageMessage):
                data = message.image_to_bytes()
                serialized.append(Message(role="user", content=message.content,images=[Image(value=data)]))
            else:
                raise ValueError(f"Unsupported message type: {type(message)}")
        return serialized

    def invoke(self, messages: list[BaseMessage], tools: list[dict]|None=None, structured_output:BaseModel|None=None) -> ChatLLMResponse:
        """Invoke Ollama API with optional native tool calling."""
        params = dict(
            model=self.model,
            stream=False,
            messages=self.serialize_messages(messages),
        )
        if tools:
            params["tools"] = self._format_tools(tools)
        if structured_output:
            params["format"] = structured_output.model_json_schema()
        else:
            params["format"] = ""
        completion=self.client.chat(**params)
        msg = completion.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    name=tc.function.name,
                    arguments=dict(tc.function.arguments) if tc.function.arguments else {},
                    raw=str(tc)
                ))
        if structured_output:
            content=structured_output.model_validate_json(msg.content)
            thinking=None
        else:
            thinking=msg.thinking if self.think else None
            content=msg.content
        return ChatLLMResponse(
            thinking=thinking,
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=ChatLLMUsage(
                prompt_tokens=completion.get("prompt_eval_count"),
                completion_tokens=completion.get("eval_count"),
                total_tokens=completion.get("eval_count")+completion.get("prompt_eval_count"),
            )
        )
