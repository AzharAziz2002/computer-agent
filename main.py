import sys
from datetime import datetime
from dotenv import load_dotenv
from medusa.auth import resolve_anthropic_auth
from medusa.orchestrator.core import Agent
from medusa.llms.anthropic import ChatAnthropic

load_dotenv()

if __name__ == "__main__":
    prompt = input("Enter prompt to execute: ")
    start_time = datetime.now()
    if not prompt.strip():
        print("Prompt can't be empty")
        sys.exit(1)

    auth = resolve_anthropic_auth()
    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        api_key=auth.api_key,
        auth_token=auth.auth_token,
        thinking_budget=-1,
    )
    agent = Agent(llm=llm, auto_minimize=True)
    agent.print_response(prompt, start_time=start_time)

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
# claude-haiku-4-5-20251001
# claude-sonnet-4-6
