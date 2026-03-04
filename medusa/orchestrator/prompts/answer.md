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