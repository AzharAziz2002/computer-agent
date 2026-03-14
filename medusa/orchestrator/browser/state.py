"""Browser state models."""

from dataclasses import dataclass, field


@dataclass
class PageInfo:
    index: int
    url: str
    title: str
    is_current: bool


@dataclass
class ElementRef:
    ref_id: str     # e.g. "e0", "e1"
    role: str       # e.g. "link", "button", "textbox"
    name: str       # e.g. "Submit", "Search"
    nth: int = 0    # disambiguation index when multiple matches
