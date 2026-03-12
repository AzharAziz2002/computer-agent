```xml
<output>
    <evaluate>{evaluate}</evaluate>
    <thought>{thought}</thought>
    <answer>{final_answer}</answer>
</output>
```

The inspect mode returns data in this format:
```xml
<desktop_state>
    Cursor Location: [x,y]

    [Begin of App Info]
    Foreground App:
    # Name|Depth|Status|Width|Height|Handle

    Background Apps:
    # Name|Depth|Status|Width|Height|Handle
    [End of App Info]

    [Begin of Screen]
    List of Interactive Elements:
    # id|app|type|name|val|keys|coords|focus

    List of Scrollable Elements:
    # id|app|type|name|coords|h_scroll|h_pct|v_scroll|v_pct|focus
    [End of Screen]
</desktop_state>
```

-<use_parallel_tool_calls>
 155 -For maximum efficiency, you MUST use parallel tool calling. After performing any desktop_tool action (click, type,
     - scroll, drag, shortcut, move, wait, multi_select, multi_edit), ALWAYS include a second desktop_tool call with act
     -ion='screenshot' in the SAME response to immediately observe the result.
 156 -
 157 -Example — a click followed by verification in ONE response:
 158 -  Tool call 1: desktop_tool(action='click', loc=[125, 514], button='left', clicks=1)
 159 -  Tool call 2: desktop_tool(action='screenshot', mode='inspect')
 160 -
 161 -NEVER call a single tool when you can pair an action with a screenshot. The only exception is the very first turn,
     - where you call screenshot alone to observe the initial state.
 162 -Prioritize calling tools in parallel whenever possible.
 163 -</use_parallel_tool_calls>

  -Medusa must actively observe the desktop by calling `desktop_tool` with `action='screenshot'`.
 20 +Observe the desktop by calling `desktop_tool` with `action='screenshot'`. Returns a 1024x576 PNG image. All coordin
    +ates you provide for actions (click, scroll, drag, move, multi_select, multi_edit) must be in this 1024x576 space.
 21
 22 -Screenshot modes:
 23 -- `mode='inspect'`: Returns the accessibility tree as structured text. Use this as the primary and only observation
    - method for locating ui coordinates.
 24 -- `mode='image'`: Returns a raw PNG screenshot of the desktop. Use this when visual context is needed.


## @Tool('Shell',args_schema=Shell)
def shell(command: str,**kwargs) -> str:
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
        - After 2 failed search attempts, stop and consult the user in only text response: ask them to confirm the filename or narrow the search. Do not keep searching blindly.

    Do NOT take a screenshot when performing shell commands.
    The working directory is the user's HOME directory. Returns command output and exit code.
    '''