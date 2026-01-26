import os
import asyncio
import json
import keyboard, threading
import time
from dotenv import load_dotenv
import win32gui, win32con
from run import run_tool
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, cast
from config import (
    MODEL,
    BETAS,
    TOOL,
    THINKING,
    MAX_TOKENS,
    WIDTH_PX,
    HEIGHT_PX,
)
from anthropic import Anthropic
from anthropic.types.beta import (    
    BetaContentBlockParam,   
    BetaMessageParam,   
    BetaToolResultBlockParam,
    BetaToolUseBlockParam,
)


SYSTEM_PROMPT = f"""
You are utilising Windows 11 computer. 
You can interact with the desktop environment using mouse and keyboard actions, and you can take screenshots.

### Rules & Capabilities
- You do not have access to a terminal, command line. 
- To launch applications, you must click on desktop icons or use the Start menu.
- The current screen resolution is {WIDTH_PX}x{HEIGHT_PX}.
- You can:
  * Move the mouse to specific coordinates
  * Perform clicks (left, right, double, middle)
  * use keyboard shortcuts
  * Type text or send keystrokes
  * Take screenshots of the current screen

### Best Practices
1. **Locating elements**: Always check the latest screenshot to determine the coordinates of icons, buttons, or links before clicking.
2. **Click accuracy**: Position the cursor so the *tip* is in the center of the target element (icon, button, link). Avoid clicking edges unless explicitly asked.
3. **Error recovery**: If a program doesn’t open after a click , adjust the cursor slightly so the tip falls directly on the visible part of the element, then retry. If app don't have close window sign then use key .

Important: "For desktop and Windows Explorer, opening apps, folders and files requires a double-click, not a single left-click.
Use single clicks only for buttons, menus,checkboxes, or taskbar icons etc.
Do not use wait actions for directories to open, only for apps to load.
Do not use wait action after every click."

### Goal
Reliably control the Windows 11 desktop by reasoning about screenshots and performing precise mouse/keyboard actions.
"""
stop_flag = False
async def ClaudeModel(prompt:str) -> str:
    load_dotenv()
    api_key=os.environ.get("CLAUDE_API_KEY")    
    threading.Thread(target=stop_execution, daemon=True).start()
    client = Anthropic(api_key=api_key)
    messages: list[BetaMessageParam] = [
        {"role": "user", "content": [{"type": "text", "text": prompt}]}
    ]   


    while(True):
        if stop_flag:
            print("[!] Program stopped by user.")
            break        
        
        prompt_cache(messages)        
        context_images_filter(messages, images_to_keep=2, min_removal_threshold=1)
        
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,        
            messages=messages,
            tools=TOOL,
            betas=BETAS,
            thinking=THINKING,        
        )

        response_content = response.content
        messages.append({"role": "assistant", "content": response_content})

            
        tool_results: list[BetaToolResultBlockParam] = []
        previous_block = None

        for block in response_content:

            if block.type == "text":
                previous_block = block
                continue

            if block.type == "tool_use":
                # print Claude reasoning if any
                if previous_block:
                    print("\n=== Claude Reason ===")
                    print(previous_block.text)
                    previous_block = None

                print("\n=== Tool Call Detected ===")
                print(json.dumps(block, indent=2, default=str))

                result = await run_tool(block.name, block.input)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result["content"]
                })
        
        if not tool_results:            
            final_text = ""
            for block in response_content:
                if block.type == "text":
                    final_text += block.text + "\n"
            return final_text.strip()        
       
        messages.append({"role": "user", "content": tool_results})

def minimize_window():
    hwnd = win32gui.GetForegroundWindow()
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

def stop_execution():    
    global stop_flag
    keyboard.wait("q")
    print("\nProgram stopped. Pressed (q). Exiting")
    stop_flag = True

def context_images_filter(
    messages: list[BetaMessageParam],
    images_to_keep: int,
    min_removal_threshold: int = 1,
):   

    if images_to_keep is None or images_to_keep <= 0:
        return messages    
    tool_result_blocks = cast(
        list[BetaToolResultBlockParam],
        [
            item
            for message in messages
            for item in (
                message["content"] if isinstance(message["content"], list) else []
            )
            if isinstance(item, dict) and item.get("type") == "tool_result"
        ],
    )    
    total_images = sum(
        1
        for tool_result in tool_result_blocks
        for content in tool_result.get("content", [])
        if isinstance(content, dict) and content.get("type") == "image"
    )    
    images_to_remove = total_images - images_to_keep
    images_to_remove -= images_to_remove % min_removal_threshold    
    for tool_result in tool_result_blocks:
        if isinstance(tool_result.get("content"), list):
            new_content = []
            for content in tool_result["content"]:
                if isinstance(content, dict) and content.get("type") == "image":
                    if images_to_remove > 0:
                        images_to_remove -= 1
                        continue  
                new_content.append(content)
            tool_result["content"] = new_content

    return messages

def prompt_cache(messages: list[BetaMessageParam], max_cache_blocks: int = 4):    
    count = 0
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], list):
            last_block = message["content"][-1]
            if count < max_cache_blocks:
                last_block["cache_control"] = {"type": "ephemeral"}
                count += 1
            else:
                if isinstance(last_block, dict) and "cache_control" in last_block:
                    del last_block["cache_control"]

                    



