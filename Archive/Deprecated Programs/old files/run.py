import asyncio
import traceback
from typing import Any, Dict

from tools.computer import ComputerTool  


computer_tool = ComputerTool()
TOOLS = {
    "computer": computer_tool,
}

async def run_tool(name: str, input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a tool by name with given input.
    Handles errors and always returns a dict Claude can understand.
    """
    try:
        if name not in TOOLS:
            return {
                "error": f"Unknown tool: {name}",
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            }
        tool = TOOLS[name]
        
        result = await tool(**input)

        content_blocks = []
        if result.get("output"):
            content_blocks.append({"type": "text", "text": result["output"]})
        if result.get("error"):
            content_blocks.append({"type": "text", "text": result["error"]})
        if result.get("base64_image"):
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",  
                    "data": result["base64_image"]
                }
            })
        return {
            "content": content_blocks
        }

    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {e}",
            "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}]
        }

# async def main():
#     res = await run_tool(input={'action': 'mouse_move','coordinate': (1741,13)}, name='computer')
#     print(res['content'])

# if __name__ == "__main__":
#     asyncio.run(main())