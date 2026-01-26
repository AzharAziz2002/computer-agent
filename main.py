import asyncio
from agent import ClaudeModel,minimize_window
import sys

if __name__ == "__main__":
    prompt = input("Enter prompt to execute: ")
    if not prompt.strip():
        print("Prompt can't be empty")
        sys.exit(1)
    minimize_window()
    result = asyncio.run(ClaudeModel(prompt))

    print("\n=== Final Result ===")
    print(result)
