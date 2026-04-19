from pydantic import BaseModel

class ChatLLMUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    image_tokens: int|None = None

class ToolCall(BaseModel):
    """Represents a single tool call from the LLM response."""
    id: str|None = None
    item_id: str|None = None  # Provider item ID (e.g. Codex 'fc_...' ID)
    name: str
    arguments: dict
    raw: str|None = None  # Provider's raw response object repr

class ChatLLMResponse(BaseModel):
    content: str|BaseModel|None = None
    thinking: str|None = None
    usage: ChatLLMUsage|None = None
    tool_calls: list[ToolCall]|None = None
