from pydantic import Field
from typing import Literal, Optional
from medusa.orchestrator.tools.base import SharedBaseModel


class DesktopAction(SharedBaseModel):
    """Unified schema for all desktop interaction actions."""

    action: Literal['click', 'type', 'scroll', 'drag', 'move', 'shortcut', 'hold_key', 'wait', 'multi_select', 'multi_edit', 'screenshot'] = Field(
        ..., description="click: click at loc | type: type text into focused element | scroll: scroll at loc | drag: drag cursor to loc | move: move cursor without clicking | shortcut: press key combination | hold_key: hold a key down for duration seconds | wait: pause execution | multi_select: click multiple locs with optional Ctrl | multi_edit: click-and-type into multiple fields | screenshot: screenshot of the screen."
    )
    # Shared coordinate field (click, scroll, drag, move, multi_select)
    loc: Optional[tuple[int, int]] = Field(
        None, description="(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required for click, drag, move. Relevant for scroll action."
    )
    # click params
    button: Literal['left', 'right', 'middle'] = Field(
        'left', description="[click] Mouse button: 'left' for selection, 'right' for context menu, 'middle' for browser actions"
    )
    clicks: Literal[1, 2] = Field(
        1, description="[click] Click count: 1=single click, 2=double click."
    )
    modifier: Optional[str] = Field(
        None, description="[click, drag, scroll] Key to hold while performing the action, e.g. 'ctrl' for ctrl+click or ctrl+scroll, 'shift' for shift+click or shift+drag"
    )
    # type / shortcut / hold_key params
    text: Optional[str] = Field(
        None, description="[type] text to type into focused element | [shortcut] key combo e.g. 'ctrl+c', 'alt+tab', 'enter' | [hold_key] key to hold e.g. 'shift', 'ctrl'"
    )
    clear: Literal['true', 'false'] = Field(
        'false', description="[type] Set 'true' to select-all. Use when replacing field content entirely"
    )
    caret_position: Literal['start', 'idle', 'end'] = Field(
        'idle', description="[type] Optional before typing: 'start'=beginning of field, 'end'=end of field, 'idle'=no movement"
    )
    press_enter: Literal['true', 'false'] = Field(
        'false', description="[type] Set 'true' after typing. Use for search bars, address bars, or form submission"
    )
    # scroll params
    scroll_direction: Literal['up', 'down', 'left', 'right'] = Field(
        'down', description="[scroll] Scroll direction"
    )
    wheel_times: int = Field(
        1, description="[scroll] Number of scroll wheel increments (1 wheel ~ 12 lines)"
    )
    # wait params
    duration: Optional[int] = Field(
        None, description="[wait , hold_key] Pause duration in seconds"
    )
    # multi_select params
    press_ctrl: Literal['true', 'false'] = Field(
        'false', description="[multi_select] Hold Ctrl for additive selection"
    )
    # shared for multi_select (list[tuple[int,int]]) and multi_edit (list[tuple[int,int,str]])
    elements: Optional[list] = Field(
        None, description="[multi_select] List of (x,y) coordinates. [multi_edit] List of (x,y,text) tuples"
    )
