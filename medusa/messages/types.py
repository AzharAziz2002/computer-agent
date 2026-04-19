from pydantic import BaseModel
from textwrap import shorten
from typing import Literal
from PIL.Image import Image
from io import BytesIO
import base64

class BaseMessage(BaseModel):
    role: Literal["system", "human", "ai", "tool"]
    content: str
    
    class Config:
        arbitrary_types_allowed = True

class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    content: str

    def __repr__(self) -> str:
        return f"SystemMessage(content={self.content})"

class HumanMessage(BaseMessage):
    role: Literal["user"] = "human"
    content: str

    def __repr__(self) -> str:
        return f"HumanMessage(content={self.content})"
    
class ImageMessage(BaseMessage):
    role: Literal["human"] = "human"
    content: str
    image: Image|None
    mime_type: str="image/png"
    
    def image_to_base64(self) -> str:
        image_bytes = self.image_to_bytes()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        return base64_image
    
    def image_to_bytes(self) -> bytes:
        buffered = BytesIO()
        format = self.mime_type.split("/")[-1]
        self.image.save(buffered, format=format)
        return buffered.getvalue()

    def __repr__(self) -> str:
        return f"ImageMessage(content={self.content}, image={shorten(self.image, width=30, placeholder='...')}, mime_type={self.mime_type})"

class AIMessage(BaseMessage):
    role: Literal["ai"] = "ai"
    content: str

    def __repr__(self) -> str:
        return f"AIMessage(content={self.content})"

class ToolCallMessage(BaseMessage):
    """AI response that includes a tool call."""
    role: Literal["ai"] = "ai"
    content: str = ""
    tool_call_id: str|None = None
    tool_item_id: str|None = None  # Provider item ID (e.g. Codex 'fc_...' ID)
    tool_name: str = ""
    tool_input: dict = {}

    def __repr__(self) -> str:
        return f"ToolCallMessage(tool={self.tool_name}, input={self.tool_input})"

class ToolResultMessage(BaseMessage):
    """Tool execution result sent back to the model."""
    role: Literal["tool"] = "tool"
    content: str = ""
    tool_call_id: str|None = None
    tool_name: str = ""
    image: Image|None = None
    mime_type: str = "image/png"
    cache_control: dict|None = None  # e.g. {"type": "ephemeral"} — set by ContextManager

    def image_to_base64(self) -> str:
        buffered = BytesIO()
        fmt = self.mime_type.split("/")[-1]
        self.image.save(buffered, format=fmt)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def __repr__(self) -> str:
        return f"ToolResultMessage(tool={self.tool_name}, content={self.content[:50]})"