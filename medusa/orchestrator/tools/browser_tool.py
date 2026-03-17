from medusa.orchestrator.tools.browser_schema import BrowserAction
from medusa.orchestrator.registry.views import ToolResult
from medusa.tool import Tool


@Tool('Browser', args_schema=BrowserAction)
async def browser(action: str, **kwargs) -> str:
    '''
    Automate web browser via Playwright. Provides structured access to web pages
    through an accessibility-based element reference system.

    Workflow:
        1. action='navigate' with url — go to a webpage (browser auto-starts)
        2. action='snapshot' — get the page accessibility tree with element refs [e0], [e1], ...
        3. Use refs to interact: click(ref='e3'), type(ref='e5', text='hello'), etc.
        4. action='snapshot' again after interactions to see updated page state

    Element refs (e.g. 'e0', 'e3') are assigned by snapshot and used by click, type, hover,
    select_option, scroll_to. Refs are invalidated after navigation — always take a new snapshot.

    Use browser tool instead of desktop tool for web interactions — it is more
    reliable than clicking coordinates on screen.
    '''
    from medusa.orchestrator.browser.controller import BrowserController
    ctrl: BrowserController = kwargs['browser']

    match action:
        case 'start':
            return await ctrl.start(
                channel=kwargs.get('channel'),
                user_data_dir=kwargs.get('user_data_dir'),
                headless=kwargs.get('headless'),
            )
        case 'stop':
            return await ctrl.stop()
        case 'status':
            return await ctrl.status()
        case 'navigate':
            url = kwargs.get('url')
            if not url:
                return ToolResult(is_success=False, error='url is required for navigate action.')
            return await ctrl.navigate(url, timeout_ms=kwargs.get('timeout_ms'))
        case 'go_back':
            return await ctrl.go_back()
        case 'snapshot':
            return await ctrl.snapshot(
                depth=kwargs.get('depth'),
                selector=kwargs.get('selector'),
                interactive=kwargs.get('interactive', False),
                compact=kwargs.get('compact', False),
                limit=kwargs.get('limit'),
                max_chars=kwargs.get('max_chars'),
                snapshot_format=kwargs.get('snapshot_format'),
                mode=kwargs.get('mode'),
            )
        case 'screenshot':
            image = await ctrl.screenshot(
                full_page=kwargs.get('full_page', False),
                ref=kwargs.get('ref'),
                element=kwargs.get('element'),
                img_type=kwargs.get('img_type', 'jpeg'),
            )
            return ToolResult(is_success=True, content='Browser screenshot captured.', image=image)
        case 'click':
            ref = kwargs.get('ref')
            element = kwargs.get('element')
            if not ref and not element:
                return ToolResult(is_success=False, error='ref or element required for click. Take a snapshot first.')
            return await ctrl.click(
                ref=ref,
                button=kwargs.get('button', 'left'),
                double_click=kwargs.get('double_click', False),
                modifiers=kwargs.get('modifiers'),
                element=element,
            )
        case 'type':
            ref = kwargs.get('ref')
            element = kwargs.get('element')
            text = kwargs.get('text')
            if not ref and not element:
                return ToolResult(is_success=False, error='ref or element required for type. Take a snapshot first.')
            if text is None:
                return ToolResult(is_success=False, error='text is required for type action.')
            return await ctrl.type_text(
                ref=ref, text=text,
                submit=kwargs.get('submit', False),
                slowly=kwargs.get('slowly', False),
                element=element,
            )
        case 'hover':
            ref = kwargs.get('ref')
            element = kwargs.get('element')
            if not ref and not element:
                return ToolResult(is_success=False, error='ref or element required for hover.')
            return await ctrl.hover(ref=ref, element=element)
        case 'select_option':
            ref = kwargs.get('ref')
            values = kwargs.get('values')
            if not ref:
                return ToolResult(is_success=False, error='ref is required for select_option action.')
            if not values:
                return ToolResult(is_success=False, error='values is required for select_option action.')
            return await ctrl.select_option(ref, values)
        case 'press_key':
            key = kwargs.get('key')
            if not key:
                return ToolResult(is_success=False, error='key is required for press_key action.')
            return await ctrl.press_key(key)
        case 'scroll_to':
            ref = kwargs.get('ref')
            if not ref:
                return ToolResult(is_success=False, error='ref is required for scroll_to action.')
            return await ctrl.scroll_to(ref)
        case 'tabs':
            return await ctrl.tabs()
        case 'open_tab':
            return await ctrl.open_tab(url=kwargs.get('url'))
        case 'focus_tab':
            tab_id = kwargs.get('tab_id')
            if tab_id is None:
                return ToolResult(is_success=False, error='tab_id is required for focus_tab action.')
            return await ctrl.focus_tab(tab_id)
        case 'close_tab':
            return await ctrl.close_tab(tab_id=kwargs.get('tab_id'))
        case 'evaluate':
            js = kwargs.get('js')
            if not js:
                return ToolResult(is_success=False, error='js is required for evaluate action.')
            return await ctrl.evaluate(js)
        case 'wait':
            return await ctrl.wait(
                time_ms=kwargs.get('time_ms', 1000),
                wait_text=kwargs.get('wait_text'),
                wait_text_gone=kwargs.get('wait_text_gone'),
            )
        case 'pdf':
            return await ctrl.pdf()
        case 'dialog':
            accept = kwargs.get('accept')
            if accept is None:
                return ToolResult(is_success=False, error='accept (true/false) is required for dialog action.')
            return await ctrl.dialog(
                accept=bool(accept),
                prompt_text=kwargs.get('prompt_text'),
            )
        case 'upload':
            paths = kwargs.get('paths')
            if not paths:
                return ToolResult(is_success=False, error='paths is required for upload action.')
            return await ctrl.upload(
                paths=paths,
                ref=kwargs.get('ref'),
                element=kwargs.get('element'),
                timeout_ms=kwargs.get('timeout_ms', 30000),
            )
        case 'console':
            return await ctrl.console(level=kwargs.get('level'))
        case 'drag':
            start_ref = kwargs.get('start_ref')
            end_ref = kwargs.get('end_ref')
            if not start_ref or not end_ref:
                return ToolResult(is_success=False, error='start_ref and end_ref required for drag action.')
            return await ctrl.drag(start_ref, end_ref)
        case 'fill':
            fields = kwargs.get('fields')
            if not fields:
                return ToolResult(is_success=False, error='fields is required for fill action.')
            return await ctrl.fill_fields(fields)
        case 'resize':
            width = kwargs.get('width')
            height = kwargs.get('height')
            if not width or not height:
                return ToolResult(is_success=False, error='width and height required for resize action.')
            return await ctrl.resize(int(width), int(height))
        case _:
            return ToolResult(is_success=False, error=f'Unknown browser action "{action}".')
