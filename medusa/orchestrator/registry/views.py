from pydantic import BaseModel
from typing import Any

class ToolResult(BaseModel):
    model_config = {'arbitrary_types_allowed': True}
    is_success: bool
    content: str | None = None
    error: str | None = None
    image: Any = None