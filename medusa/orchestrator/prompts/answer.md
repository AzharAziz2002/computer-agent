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