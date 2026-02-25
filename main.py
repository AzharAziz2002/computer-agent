import sys
import os
from dotenv import load_dotenv
from medusa.orchestrator.core import Agent
from medusa.llms.anthropic import ChatAnthropic

load_dotenv()

if __name__ == "__main__":
    prompt = input("Enter prompt to execute: ")
    if not prompt.strip():
        print("Prompt can't be empty")
        sys.exit(1)

    llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=os.getenv("CLAUDE_API_KEY"),
        thinking_budget=1024,
    )
    agent = Agent(llm=llm, use_vision=False, auto_minimize=True)
    agent.print_response(prompt)

# import asyncio
# from agent import ClaudeModel,minimize_window
# import sys

# if __name__ == "__main__":
#     prompt = input("Enter prompt to execute: ")
#     if not prompt.strip():
#         print("Prompt can't be empty")
#         sys.exit(1)
#     minimize_window()
#     result = asyncio.run(ClaudeModel(prompt))

#     print("\n=== Final Result ===")
#     print(result)