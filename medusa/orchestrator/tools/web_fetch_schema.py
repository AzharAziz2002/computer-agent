from pydantic import Field
from typing import Optional, Literal
from medusa.orchestrator.tools.base import SharedBaseModel


class WebFetch(SharedBaseModel):
    url: str = Field(
        ...,
        description="HTTP or HTTPS URL to fetch and extract content from",
        examples=["https://docs.python.org/3/whatsnew/3.13.html", "https://en.wikipedia.org/wiki/Python_(programming_language)"]
    )
    extract_mode: Optional[Literal['markdown', 'text']] = Field(
        'markdown',
        description="Extraction mode: 'markdown' preserves formatting, 'text' returns plain text"
    )
    max_chars: Optional[int] = Field(
        50000,
        description="Maximum characters to return (content truncated when exceeded)",
        ge=100
    )
