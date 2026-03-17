from medusa.orchestrator.tools.general_schema import App, Done, Scrape
from medusa.orchestrator.registry.views import ToolResult
from medusa.orchestrator.desktop.controller import Desktop
from medusa.tool import Tool
from typing import Literal, Optional


@Tool('Done', args_schema=Done)
def done(answer: str, **kwargs):
    '''
    Signals task completion and provides the final answer to the user.

    Use this tool when you have successfully completed the requested task and have
    a brief answer ready. The answer should include all relevant information the user requested.
    '''
    return answer


@Tool('App', args_schema=App)
def app(mode: Literal['launch', 'resize', 'switch'], name: Optional[str] = None, loc: Optional[tuple[int, int]] = None, size: Optional[tuple[int, int]] = None, **kwargs) -> str:
    '''
    Manages Windows applications through launch, resize, and window switching operations.

    Modes:
        - launch: Opens an application from the Windows Start Menu by name
        - resize: Adjusts the active application window's size and position
        - switch: Brings a specific application window into focus

    Use this tool to control application lifecycle and window management during task execution.
    '''
    desktop: Desktop = kwargs['desktop']
    return desktop.app(mode, name, loc, size)


@Tool('Scrape', args_schema=Scrape)
def scrape(url: str, **kwargs) -> str:
    '''
    Fetches webpage content and converts it to clean markdown format for analysis.

    Use cases:
        - Extract text content from webpages for processing
        - Gather information from online sources
        - Convert HTML pages to structured, readable text
        - Access web data without browser automation

    Requires full URL including protocol (http:// or https://).
    NOTE: This tool reads the visual accessibility tree (what is currently rendered on screen),
    not the raw HTML source code. It captures visible text content accurately.
    Returns structured text suitable for parsing, analysis, and information extraction.
    '''
    desktop: Desktop = kwargs['desktop']
    desktop_state = desktop.desktop_state
    if desktop_state is None:
        return ToolResult(is_success=False, error=f'Unable to scrape URL: {url}. Call screenshot first to observe the desktop.')
    tree_state = desktop_state.tree_state
    if not tree_state.dom_node:
        return ToolResult(is_success=False, error=f'Unable to scrape URL: {url}. No DOM node found.')
    dom_node = tree_state.dom_node
    vertical_scroll_percent = dom_node.vertical_scroll_percent
    content = '\n'.join([node.text for node in tree_state.dom_informative_nodes])
    header_status = "Reached top" if vertical_scroll_percent <= 0 else "Scroll up to see more"
    footer_status = "Reached bottom" if vertical_scroll_percent >= 100 else "Scroll down to see more"
    return f'URL:{url}\nContent:\n{header_status}\n{content}\n{footer_status}'
