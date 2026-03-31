from pydantic import Field
from typing import Optional
from medusa.orchestrator.tools.base import SharedBaseModel


class WebSearch(SharedBaseModel):
    query: str = Field(
        ...,
        description="Search query string",
        examples=["Python 3.13 new features", "best practices REST API design"]
    )
    count: Optional[int] = Field(
        5,
        description="Number of results to return (1-10)",
        ge=1, le=10
    )
    country: Optional[str] = Field(
        None,
        description="2-letter country code for region-specific results, e.g. 'US', 'PK', 'DE'"
    )
    search_lang: Optional[str] = Field(
        None,
        description="ISO language code for search results, e.g. 'en', 'ur', 'de'"
    )
    freshness: Optional[str] = Field(
        None,
        description="Recency filter: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year), or date range 'YYYY-MM-DDtoYYYY-MM-DD'"
    )
