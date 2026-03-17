from medusa.orchestrator.tools.shell_schema import Shell
from medusa.orchestrator.shellmiddleware.search_rules import SearchValidator
from medusa.orchestrator.shellmiddleware.command_safety import CommandGuard
from medusa.orchestrator.registry.views import ToolResult
from medusa.orchestrator.desktop.controller import Desktop
from medusa.tool import Tool

_search_validator = SearchValidator()


@Tool('Shell', args_schema=Shell)
def shell(command: str, **kwargs) -> str:
    '''
    Executes PowerShell commands. Prefer this over desktop whenever the task does not require interacting with an application's UI.

    Always use shell for:
        - File system: read, write, copy, move, delete, rename, search files and folders
        - Open files or media: with default app
        - Read file contents:
        - List directories:
        - OS tasks: processes, services, network, registry, environment, disk, system info
        - Any task expressible as a PowerShell command

    File search strategy:
        ALWAYS use fd for file searching. NEVER use Get-ChildItem to search for files — it is extremely slow and will time out on large drives. Get-ChildItem is only acceptable for listing the contents of a known directory, never for searching.

    Search rules:
        - ALWAYS include filename keywords in the search — NEVER search by extension alone.
        - Split user queries into individual keywords. Never search full phrases.
        - Apply extension filters when file type is known (pdf, video, xlsx, etc).
        - If no dir or path specified. Get all drives first: (Get-PSDrive -PSProvider FileSystem).Root — then search each one. Do not assume C drive only.
        - Never quote multi-word phrases — use separate keywords so order and spacing do not matter.

    The working directory is the user's HOME directory. Returns command output and exit code.
    '''
    verdict, reason = CommandGuard.classify(command)

    if verdict == 'block':
        return ToolResult(is_success=False, error=f'[BLOCKED] Command not permitted: {reason}')

    if verdict == 'confirm':
        if not CommandGuard.ask_user(command, reason):
            return ToolResult(is_success=False, error=f'[CANCELLED] User denied execution of command flagged as: {reason}')

    ok, msg = _search_validator.validate(command)
    if not ok:
        return ToolResult(is_success=False, error=msg)

    desktop: Desktop = kwargs['desktop']
    response, status = desktop.execute_command(command)
    output = f'Response: {response}\nStatus Code: {status}'

    stop_msg = _search_validator.track_result(command, response, status)
    if stop_msg:
        output += f'\n{stop_msg}'

    return output
