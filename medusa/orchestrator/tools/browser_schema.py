from pydantic import Field
from typing import Literal, Optional
from medusa.orchestrator.tools.base import SharedBaseModel


class BrowserAction(SharedBaseModel):
    """Schema for browser automation actions via Playwright."""

    action: Literal[
        'start', 'stop', 'status',
        'navigate', 'go_back', 'snapshot', 'screenshot',
        'click', 'type', 'hover', 'select_option', 'press_key', 'scroll_to',
        'tabs', 'open_tab', 'focus_tab', 'close_tab',
        'evaluate', 'wait', 'pdf',
        'dialog', 'upload', 'console', 'drag', 'fill', 'resize',
    ] = Field(
        ...,
        description=(
            "snapshot: accessibility tree with element refs | screenshot: capture page image | "
        )
    )
    # --- Navigation ---
    url: Optional[str] = Field(
        None, description="[navigate, open_tab] Target URL"
    )
    timeout_ms: Optional[int] = Field(
        None, description="[navigate, upload] Operation timeout in milliseconds"
    )
    # --- Element targeting ---
    ref: Optional[str] = Field(
        None, description="[click, type, hover, select_option, scroll_to, screenshot, upload] Element ref from snapshot (e.g. 'e0')"
    )
    element: Optional[str] = Field(
        None, description="[click, type, hover, screenshot, upload] CSS selector fallback when no ref available"
    )
    # --- Interaction ---
    text: Optional[str] = Field(
        None, description="[type] Text to type into the element"
    )
    key: Optional[str] = Field(
        None, description="[press_key] Key name (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown')"
    )
    values: Optional[list[str]] = Field(
        None, description="[select_option] Option values to select in dropdown"
    )
    button: Literal['left', 'right', 'middle'] = Field(
        'left', description="[click] Mouse button"
    )
    double_click: bool = Field(
        False, description="[click] Double-click"
    )
    modifiers: Optional[list[str]] = Field(
        None, description="[click] Modifier keys to hold: 'Shift', 'Control', 'Alt', 'Meta'"
    )
    submit: bool = Field(
        False, description="[type] Press Enter after typing"
    )
    slowly: bool = Field(
        False, description="[type] Type one character at a time (triggers key event handlers)"
    )
    # --- drag ---
    start_ref: Optional[str] = Field(
        None, description="[drag] Source element ref to drag from"
    )
    end_ref: Optional[str] = Field(
        None, description="[drag] Target element ref to drag to"
    )
    # --- fill ---
    fields: Optional[list[dict]] = Field(
        None, description="[fill] List of {ref, value} dicts to fill multiple form fields at once"
    )
    # --- snapshot format ---
    snapshot_format: Optional[Literal['aria', 'ai']] = Field(
        None, description="[snapshot] 'ai' uses Playwright's _snapshotForAI (more stable refs, better quality). 'aria' forces standard ariaSnapshot() YAML."
    )
    # --- snapshot mode ---
    mode: Optional[Literal['efficient', 'deep']] = Field(
        None, description="[snapshot] 'efficient' (default): 10k char limit, depth capped at 6 — fast and cheap. 'deep': 80k char limit, no depth cap — for thorough page analysis."
    )
    # --- snapshot filters ---
    depth: Optional[int] = Field(
        None, description="[snapshot] Max accessibility tree depth (0=top level only, 1=one level deep, etc.). Overrides mode default when set."
    )
    selector: Optional[str] = Field(
        None, description="[snapshot] CSS selector to use as snapshot root instead of full page"
    )
    interactive: Optional[bool] = Field(
        None, description="[snapshot] If true, return only interactive elements (buttons, inputs, links)"
    )
    compact: Optional[bool] = Field(
        None, description="[snapshot] If true, strip blank lines for a more compact output"
    )
    limit: Optional[int] = Field(
        None, description="[snapshot] Max number of interactive elements to include in output"
    )
    max_chars: Optional[int] = Field(
        None, description="[snapshot] Override character limit (efficient=10k, deep=80k). Only set when you need a custom value."
    )
    # --- screenshot ---
    full_page: bool = Field(
        False, description="[screenshot] Capture full scrollable page instead of viewport"
    )
    img_type: Optional[Literal['png', 'jpeg']] = Field(
        None, description="[screenshot] Image format: 'png' or 'jpeg' (default jpeg)"
    )
    # --- wait ---
    time_ms: Optional[int] = Field(
        None, description="[wait] Duration in milliseconds (used as timeout when waiting for text)"
    )
    wait_text: Optional[str] = Field(
        None, description="[wait] Wait until this text appears on the page"
    )
    wait_text_gone: Optional[str] = Field(
        None, description="[wait] Wait until this text disappears from the page"
    )
    # --- tabs ---
    tab_id: Optional[str] = Field(
        None, description="[focus_tab, close_tab] Stable tab ID from tabs list (e.g. 't0', 't1'). IDs never change when tabs open/close."
    )
    # --- evaluate ---
    js: Optional[str] = Field(
        None, description="[evaluate] JavaScript expression to execute in page context"
    )
    # --- dialog ---
    accept: Optional[bool] = Field(
        None, description="[dialog] REQUIRED. True=accept/OK, False=dismiss/cancel. Arms a one-shot handler — call this BEFORE the action that triggers the dialog."
    )
    prompt_text: Optional[str] = Field(
        None, description="[dialog] Text to enter into a prompt() dialog before accepting. Only applies when accept=True."
    )
    # --- upload ---
    paths: Optional[list[str]] = Field(
        None, description="[upload] File paths relative to the uploads directory (~/.medusa/uploads/)"
    )
    # --- console ---
    level: Optional[str] = Field(
        None, description="[console] Filter by log level: 'error', 'warning', 'info', 'log'"
    )
    # --- resize ---
    width: Optional[int] = Field(
        None, description="[resize] Viewport width in pixels"
    )
    height: Optional[int] = Field(
        None, description="[resize] Viewport height in pixels"
    )
    # --- start ---
    channel: Optional[str] = Field(
        None, description="[start] Browser channel: 'chrome', 'msedge', 'chromium'. Default: chrome"
    )
    user_data_dir: Optional[str] = Field(
        None, description="[start] Path to browser profile directory for persistent sessions"
    )
    headless: Optional[bool] = Field(
        None, description="[start] Run in headless mode (no visible window)"
    )




# "start: launch browser | stop: close browser | status: check state | "
#             "navigate: go to URL | go_back: previous page | "
#             "snapshot: accessibility tree with element refs | screenshot: capture page image | "
#             "click: click element by ref | type: type into element by ref | "
#             "hover: hover element | select_option: select dropdown value | "
#             "press_key: press keyboard key | scroll_to: scroll element into view | "
#             "tabs: list open tabs | open_tab: new tab | focus_tab: switch tab | close_tab: close tab | "
#             "evaluate: run JavaScript | wait: pause or wait for text condition | pdf: save as PDF | "
#             "dialog: arm handler for next browser alert/confirm/prompt | "
#             "upload: upload files to a file input (arms chooser then triggers click) | "
#             "console: read captured browser console messages | "
#             "drag: drag from one element ref to another | "
#             "fill: fill multiple form fields in one call | "
#             "resize: resize the browser viewport"