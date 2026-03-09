from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional

class SharedBaseModel(BaseModel):

    @model_validator(mode='before')
    def check_required_fields(cls, data):
        missing = [
            name for name, field in cls.model_fields.items()
            if field.is_required() and name not in data
        ]
        if missing:
            field_list = ", ".join(missing)
            raise ValueError(f"The following required fields are missing: {field_list}")
        return data

    class Config:
        extra = 'allow'

class App(SharedBaseModel):
    mode: Literal['launch', 'resize', 'switch'] = Field(
        ...,
        description="Operation mode: 'launch' opens app from Start Menu, 'resize' adjusts active window size/position, 'switch' brings specific window into focus",
        examples=['launch']
    )
    name: Optional[str] = Field(
        description="Exact application name as it appears in Start Menu or window title (required for launch/switch modes)",
        examples=['notepad', 'chrome', 'New tab - Personal - Microsoft Edge'],
        default=None
    )
    loc: Optional[tuple[int, int]] = Field(
        description="Target (x, y) coordinates for window top-left corner position (required for resize mode)",
        examples=[(0, 0)],
        default=None
    )
    size: Optional[tuple[int, int]] = Field(
        description="Target (width, height) dimensions in pixels for window size (required for resize mode)",
        examples=[(1920, 1080)],
        default=None
    )

class Done(SharedBaseModel):
    answer: str = Field(
        ...,
        description="Comprehensive final answer in markdown format containing all requested information and task results",
        examples=["## Task Completed\n\nThe task has been completed successfully. Here are the results:\n- Item 1\n- Item 2"]
    )

class Memory(SharedBaseModel):
    mode: Literal['view', 'read', 'write', 'delete', 'update'] = Field(
        description="Operation mode: view (list files), read (get content), write (create), update (modify), delete (remove)"
    )
    path: Optional[str] = Field(
        None,
        description="Relative path from .memories directory (e.g., 'notes.md' or 'project/data.md'). Required for read, write, update, delete modes."
    )
    content: Optional[str] = Field(
        None,
        description="Content to write or insert. Required for write mode and insert operation."
    )
    operation: Optional[Literal['replace', 'insert']] = Field(
        'replace',
        description="Update operation type: replace (str replacement), insert (at line)"
    )
    old_str: Optional[str] = Field(
        None,
        description="String to find and replace. Required when operation='replace'."
    )
    new_str: Optional[str] = Field(
        None,
        description="String to replace old_str with. Required when operation='replace'."
    )
    line_number: Optional[int] = Field(
        None,
        description="Line number for insertion (0-indexed). Required when operation='insert'."
    )
    read_range: Optional[tuple[int, int]] = Field(
        None,
        description="Range of lines to read (start, end) - both 0-indexed, end is exclusive. Example: (0, 10) reads lines 0-9. Optional for read mode."
    )

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

class Shell(SharedBaseModel):
    command: str = Field(
        ...,
        description="PowerShell command to execute. Working directory is set to user's HOME. Returns output and exit status code",
        examples=[
            'Get-Process',
            'ls',
            'Get-ChildItem -Path C:\\Users -Recurse',
            'echo "Hello World"'
        ]
    )

class Scrape(SharedBaseModel):
    url: str = Field(
        ...,
        description="Full webpage URL including protocol (http:// or https://) to fetch and convert to markdown format",
        examples=['https://google.com', 'https://example.com/page', 'http://localhost:8080']
    )