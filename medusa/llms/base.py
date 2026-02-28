from typing import Protocol,runtime_checkable,overload
from medusa.llms.views import ChatLLMResponse
from medusa.messages import BaseMessage
from pydantic import BaseModel

@runtime_checkable
class BaseChatLLM(Protocol):

    @property
    def model_name(self) -> str:
        ...

    @property
    def provider(self) -> str:
        ...

    def invoke(self, messages: list[BaseMessage], tools: list[dict]|None=None, structured_output: BaseModel|None=None) -> ChatLLMResponse:
        ...
