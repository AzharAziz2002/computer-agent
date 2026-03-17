from medusa.orchestrator.tools.desktop_schema import DesktopAction
from medusa.orchestrator.registry.views import ToolResult
from medusa.orchestrator.desktop.controller import Desktop
from medusa.tool import Tool
from time import sleep


@Tool('Desktop', args_schema=DesktopAction)
def desktop(action: str, **kwargs) -> str:
    '''
    "Execute GUI actions on the desktop: mouse clicks, keyboard, scrolling, and screenshots."
    * Some applications may take time to start or process actions, so use action='wait' to see the results of your actions. E.g. if you click on Firefox and a window doesn't open, try waiting before taking another screenshot.
    * The screen's resolution is 1024x576.* The display number is 1
    * You should ONLY call move if you intend to hover over an element without clicking. Otherwise, use the click or drag functions directly.
    * Whenever you intend to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.
    * If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your click location so that the tip of the cursor visually falls on the element that you want to click.
    * Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.

    Use action='wait' when an action triggers a process that takes time to complete—such as opening apps, loading webpages, submitting forms, or UI transitions.

    <use_parallel_tool_calls>
    MUST use parallel tool calls wherever possible. Batch actions that logically follow each other without needing to inspect the result in between.



    Wait in parallel — always pair wait with screenshot so both execute together:
      [{action='wait', duration=2}, {action='screenshot'}]

    Example 1 — click something that loads (profile, app, page):
      [{action='click', loc=(x,y)}, {action='wait', duration=2}, {action='screenshot'}]

    Example 2 — click + type
      [{action='click', loc=(x,y)}, {action='type', text='hello', press_enter='true'}, {action='screenshot'}]

    Example 3 — first screenshot after user query (single only):
      [{action='screenshot'}]

    Every response that performs an action MUST include action='screenshot' in the same parallel batch.
    </use_parallel_tool_calls>
    '''
    dt: Desktop = kwargs['desktop']
    match action:
        case 'click':
            loc = kwargs['loc']
            button = kwargs.get('button', 'left')
            clicks = kwargs.get('clicks', 1)
            modifier = kwargs.get('modifier')
            dt.click(loc, button, clicks, modifier)
            num = {1: 'Single', 2: 'Double'}.get(clicks, str(clicks))
            mod_str = f' with {modifier} held' if modifier else ''
            return f'{num} {button} clicked at ({loc[0]},{loc[1]}){mod_str}.'

        case 'type':
            text = kwargs['text']
            dt.type(text,
                    caret_position=kwargs.get('caret_position', 'idle'),
                    clear=kwargs.get('clear', 'false'),
                    press_enter=kwargs.get('press_enter', 'false'))
            return f'Typed "{text}" into focused element.'

        case 'scroll':
            loc = kwargs.get('loc')
            scroll_direction = kwargs.get('scroll_direction', 'down')
            wt = kwargs.get('wheel_times', 1)
            modifier = kwargs.get('modifier')
            resp = dt.scroll(loc, scroll_direction, wt, modifier)
            return resp or f'Scrolled {scroll_direction} by {wt} wheel times.'

        case 'drag':
            loc = kwargs['loc']
            modifier = kwargs.get('modifier')
            dt.drag(loc, modifier)
            mod_str = f' with {modifier} held' if modifier else ''
            return f'Dragged to ({loc[0]},{loc[1]}){mod_str}.'

        case 'move':
            loc = kwargs['loc']
            dt.move(loc)
            return f'Moved cursor to ({loc[0]},{loc[1]}).'

        case 'shortcut':
            shortcut = kwargs['text']
            dt.shortcut(shortcut)
            return f'Pressed {shortcut}.'

        case 'hold_key':
            key = kwargs['text']
            duration = kwargs['duration']
            dt.hold_key(key, duration)
            return f'Held {key} for {duration}s.'

        case 'wait':
            duration = kwargs['duration']
            sleep(duration)
            return f'Waited for {duration} seconds.'

        case 'multi_select':
            dt.multi_select(kwargs.get('press_ctrl', 'false'), kwargs['elements'])
            return f'Multi-selected {len(kwargs["elements"])} elements.'

        case 'multi_edit':
            dt.multi_edit(kwargs['elements'])
            return f'Multi-edited {len(kwargs["elements"])} elements.'

        case 'screenshot':
            return ToolResult(is_success=True, content="Screenshot captured.", image=dt.scale_image())
