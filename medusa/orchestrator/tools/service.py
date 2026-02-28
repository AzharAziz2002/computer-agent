from medusa.orchestrator.tools.views import DesktopAction, Scrape, Done, Shell, Memory, App
from medusa.orchestrator.tools.guard import CommandGuard
from medusa.orchestrator.desktop.controller import Desktop
from typing import Literal,Optional
from medusa.tool import Tool
from pathlib import Path
from time import sleep

memory_path=Path.cwd()/'.memories'

@Tool('Done Tool',args_schema=Done)
def done_tool(answer:str,**kwargs):
    '''
    Signals task completion and provides the final answer to the user.
    
    Use this tool when you have successfully completed the requested task and have 
    a comprehensive answer ready. The answer should be well-formatted in markdown 
    and include all relevant information the user requested.
    '''
    return answer

@Tool('App Tool',args_schema=App)
def app_tool(mode:Literal['launch','resize','switch'],name:Optional[str]=None,loc:Optional[tuple[int,int]]=None,size:Optional[tuple[int,int]]=None,**kwargs)->str:
    '''
    Manages Windows applications through launch, resize, and window switching operations.
    
    Modes:
        - launch: Opens an application from the Windows Start Menu by name
        - resize: Adjusts the active application window's size and position
        - switch: Brings a specific application window into focus
    
    Use this tool to control application lifecycle and window management during task execution.
    '''
    desktop:Desktop=kwargs['desktop']
    return desktop.app(mode,name,loc,size)

@Tool('Memory Tool',args_schema=Memory)
def memory_tool(mode: Literal['view','read','write','delete','update'],path: Optional[str] = None,
    content: Optional[str] = None,operation: Optional[Literal['replace', 'insert']] = 'replace',
    old_str: Optional[str] = None,new_str: Optional[str] = None,line_number: Optional[int] = None,
    read_range: Optional[tuple[int, int]] = None,**kwargs) -> str:
    '''
    Persistent file-based storage system for managing information across different task stages.
    
    Use this tool to:
        - Store important findings and data as md files in the .memories directory
        - Maintain context across complex multi-step operations
        - Track progress of plans and accumulate knowledge during task execution
        - Cache information that may be referenced in future steps
    
    Modes:
        - write: Create a new memory file (returns assigned path)
        - view: List all directories and memory files in the .memories directory
        - read: Retrieve contents of a specific memory file by path
            * read_range: Optional (start, end) tuple to read specific line range (0-indexed, end exclusive)
        - update: Modify contents of an existing memory file by path
            Operations:
            * replace: Replace old_str with new_str (requires old_str and new_str)
            * insert: Insert content at line_number (requires line_number and content)
        - delete: Remove a memory file by path
    
    All data is persisted as files in the .memories directory, ensuring information
    survives across sessions and can be shared between different task stages.
    
    Essential for tasks requiring information persistence and cross-stage data sharing.
    '''
    match mode:
        case 'view':
            files = (Path(path) if path else memory_path).rglob('*.md')
            result = '\n'.join([f'{i+1}. {file.relative_to(memory_path.parent).as_posix()}' 
                               for i, file in enumerate(files)])
            return result if result else "No memory files found."
        
        case 'write':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            return f'{file_path.name} created in {file_path.parent.relative_to(memory_path.parent).as_posix()}.'
        
        case 'read':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return f'Error: {file_path.name} not found.'
            
            file_content = file_path.read_text(encoding='utf-8')
            
            if read_range:
                start, end = read_range
                lines = file_content.splitlines()
                
                if start < 0 or start >= len(lines):
                    return f'Error: start line {start} out of range (0-{len(lines)-1}).'
                if end < start or end > len(lines):
                    return f'Error: end line {end} out of range ({start}-{len(lines)}).'
                
                selected_lines = lines[start:end]
                return f"File: {file_path.relative_to(memory_path.parent).as_posix()}\nLines {start}-{end-1}:\n" + '\n'.join(selected_lines)
            
            return f"File: {file_path.relative_to(memory_path.parent).as_posix()}\nContent:\n{file_content}"
        
        case 'update':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return f'Error: {file_path.name} not found. Use "write" mode to create a new file.'
            
            current_content = file_path.read_text(encoding='utf-8')
            
            match operation:
                case 'replace':
                    if not old_str or not new_str:
                        return 'Error: both old_str and new_str are required for replace operation.'
                    if old_str not in current_content:
                        return f'Error: "{old_str}" not found in file.'
                    
                    new_content = current_content.replace(old_str, new_str)
                    file_path.write_text(new_content, encoding='utf-8')
                    return f'{file_path.name} updated: replaced "{old_str[:50]}..." with "{new_str[:50]}...".'
                
                case 'insert':
                    if line_number is None:
                        return 'Error: line_number is required for insert operation.'
                    if not content:
                        return 'Error: content is required for insert operation.'
                    
                    lines = current_content.splitlines(keepends=True)
                    if line_number < 0 or line_number > len(lines):
                        return f'Error: line_number {line_number} out of range (0-{len(lines)}).'
                    
                    lines.insert(line_number, content + '\n' if not content.endswith('\n') else content)
                    new_content = ''.join(lines)
                    file_path.write_text(new_content, encoding='utf-8')
                    return f'{file_path.name} updated: inserted content at line {line_number}.'
                
                case _:
                    return f'Error: Unknown operation "{operation}".'
        
        case 'delete':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return f'Error: {file_path.name} not found.'
            
            file_path.unlink()
            return f'{file_path.name} deleted from {file_path.parent.relative_to(memory_path.parent).as_posix()}.'
        
    return "Invalid mode. Use 'view', 'write', 'read', 'update', or 'delete'."

@Tool('Shell Tool',args_schema=Shell)
def shell_tool(command: str,**kwargs) -> str:
    '''
    Executes PowerShell commands and returns output with status codes.

    Use this tool to:
        - Run Windows system commands and scripts
        - Query system information and configurations
        - Automate file operations and system tasks
        - Access Windows management utilities

    The working directory is set to the user's HOME directory by default.
    Returns both command output and exit status code for error handling.
    '''
    verdict, reason = CommandGuard.classify(command)

    if verdict == 'block':
        return f'[BLOCKED] Command not permitted: {reason}'

    if verdict == 'confirm':
        if not CommandGuard.ask_user(command, reason):
            return f'[CANCELLED] User denied execution of command flagged as: {reason}'

    desktop:Desktop=kwargs['desktop']
    response,status=desktop.execute_command(command)
    return f'Response: {response}\nStatus Code: {status}'

@Tool('Desktop Tool',args_schema=DesktopAction)
def desktop_tool(action:str,**kwargs)->str:
    '''
    Unified desktop interaction tool for all mouse, keyboard, and UI actions.
    Actions:
             - click: Click at coordinates (loc, button, clicks)
             - type: Type text into element (loc, text, clear, caret_position, press_enter)
             - scroll: Scroll content (loc, scroll_type, direction, wheel_times)
             - drag: Drag from current cursor to destination (loc)
             - move: Move cursor without clicking (loc)
             - shortcut: Press keyboard shortcut (shortcut)
             - wait: Pause execution (duration)
             - multi_select: Select multiple elements (press_ctrl, elements)
             - multi_edit: Type into multiple fields (elements)
    '''
    desktop:Desktop=kwargs['desktop']
    match action:
        case 'click':
            loc=kwargs['loc']
            button=kwargs.get('button','left')
            clicks=kwargs.get('clicks',1)
            desktop.click(loc,button,clicks)
            num={1:'Single',2:'Double'}.get(clicks,str(clicks))
            return f'{num} {button} clicked at ({loc[0]},{loc[1]}).'

        case 'type':
            loc=kwargs['loc']
            text=kwargs['text']
            desktop.type(loc,text,kwargs.get('clear','false'),
                         kwargs.get('caret_position','idle'),
                         kwargs.get('press_enter','false'))
            return f'Typed {text} at ({loc[0]},{loc[1]}).'

        case 'scroll':
            loc=kwargs.get('loc')
            st=kwargs.get('scroll_type','vertical')
            direction=kwargs.get('direction','down')
            wt=kwargs.get('wheel_times',1)
            resp=desktop.scroll(loc,st,direction,wt)
            return resp or f'Scrolled {st} {direction} by {wt} wheel times.'

        case 'drag':
            loc=kwargs['loc']
            desktop.drag(loc)
            return f'Dragged to ({loc[0]},{loc[1]}).'

        case 'move':
            loc=kwargs['loc']
            desktop.move(loc)
            return f'Moved cursor to ({loc[0]},{loc[1]}).'

        case 'shortcut':
            shortcut=kwargs['shortcut']
            desktop.shortcut(shortcut)
            return f'Pressed {shortcut}.'

        case 'wait':
            duration=kwargs['duration']
            sleep(duration)
            return f'Waited for {duration} seconds.'

        case 'multi_select':
            desktop.multi_select(kwargs.get('press_ctrl','false'),kwargs['elements'])
            return f'Multi-selected {len(kwargs["elements"])} elements.'

        case 'multi_edit':
            desktop.multi_edit(kwargs['elements'])
            return f'Multi-edited {len(kwargs["elements"])} elements.'

@Tool('Scrape Tool',args_schema=Scrape)
def scrape_tool(url:str,**kwargs)->str:
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
    desktop:Desktop=kwargs['desktop']
    desktop_state=desktop.desktop_state
    tree_state=desktop_state.tree_state
    if not tree_state.dom_node:
        return f'Unable to scrape URL: {url}. No DOM node found.'
    dom_node=tree_state.dom_node
    vertical_scroll_percent=dom_node.vertical_scroll_percent
    content='\n'.join([node.text for node in tree_state.dom_informative_nodes])
    header_status = "Reached top" if vertical_scroll_percent <= 0 else "Scroll up to see more"
    footer_status = "Reached bottom" if vertical_scroll_percent >= 100 else "Scroll down to see more"
    return f'URL:{url}\nContent:\n{header_status}\n{content}\n{footer_status}'