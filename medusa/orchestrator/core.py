from medusa.orchestrator.tools.service import (desktop_tool, shell_tool, done_tool, memory_tool,
app_tool, scrape_tool)
from medusa.messages import SystemMessage, HumanMessage, AIMessage, ToolCallMessage, ToolResultMessage
from medusa.telemetry.views import AgentTelemetryEvent
from medusa.telemetry.tracker import ProductTelemetry
from medusa.orchestrator.views import AgentResult, AgentStep
from medusa.orchestrator.registry.core import Registry
from medusa.orchestrator.watchdog.observer import WatchDog
from medusa.orchestrator.desktop.controller import Desktop
from medusa.orchestrator.desktop.state import Browser
from medusa.orchestrator.prompts.generator import Prompt
from medusa.orchestrator.context import ContextManager
from medusa.logs.logger import SessionLogger
from medusa.llms.base import BaseChatLLM
from contextlib import nullcontext
from rich.markdown import Markdown
from rich.console import Console

class Agent:
    def __init__(self, instructions: list[str]=[], browser: Browser=Browser.EDGE, llm: BaseChatLLM=None, max_consecutive_failures: int=3, use_vision: bool=False, auto_minimize: bool=False, enable_telemetry: bool=False):
        self.name = 'Medusa'
        self.description = 'An agent that can interact with GUI elements on Windows OS'
        self.registry = Registry([
            desktop_tool, app_tool, shell_tool, done_tool,
            memory_tool, scrape_tool
        ])
        self.instructions = instructions
        self.browser = browser
        self.agent_step = AgentStep()
        self.max_consecutive_failures = max_consecutive_failures
        self.auto_minimize = auto_minimize
        self.use_vision = use_vision
        self.llm = llm
        self.telemetry = ProductTelemetry() if enable_telemetry else None
        self.watchdog = WatchDog()
        self.desktop = Desktop()
        self.console = Console()

    def invoke(self, query: str, start_time=None) -> AgentResult:
        """Invoke the agent with a query."""
        if query.strip() == '':
            return AgentResult(is_done=False, error="Query is empty. Please provide a valid query.")
        session_log = SessionLogger(
            query=query,
            model_name=self.llm.model_name if self.llm else "unknown",
            start_time=start_time,
        )
        try:
            with (self.desktop.auto_minimize() if self.auto_minimize else nullcontext()):
                self.watchdog.set_focus_callback(self.desktop.tree._on_focus_change)
                self.watchdog.set_property_callback(self.desktop.tree._on_property_change)
                with self.watchdog:
                    language = self.desktop.get_default_language()
                    tools_schema = self.registry.get_tools_schema()
                    answer = None
                    system_prompt = Prompt.system_prompt(
                        desktop=self.desktop, browser=self.browser,
                        language=language, instructions=self.instructions
                    )
                    context = ContextManager(block_limit=4, screenshot_limit=1, cache_query=False)
                    context.append(SystemMessage(content=system_prompt))
                    context.append(HumanMessage(content=query))
                    session_log.mark_ready()

                    while True:
                        self.agent_step.step_increment()

                        # Retry logic for LLM failures
                        llm_response = None
                        for consecutive_failures in range(1, self.max_consecutive_failures + 1):
                            try:
                                llm_response = self.llm.invoke(context.messages, tools=tools_schema)
                                break
                            except Exception as e:
                                if consecutive_failures == self.max_consecutive_failures:
                                    if self.telemetry:
                                        self.telemetry.capture(AgentTelemetryEvent(
                                            query=query, error=str(e),
                                            steps=self.agent_step.steps,
                                            use_vision=self.use_vision,
                                            model=self.llm.model_name,
                                            provider=self.llm.provider,
                                            is_success=False
                                        ))
                                    result = AgentResult(is_done=False, error=str(e))
                                    return result

                        if not llm_response or not llm_response.tool_calls:
                            answer = llm_response.content if llm_response else ""
                            session_log.log_response(
                                step=self.agent_step.steps,
                                content=answer,
                                thinking=llm_response.thinking if llm_response else None,
                                tool_calls=None,
                                usage=llm_response.usage if llm_response else None
                            )
                            break

                        # Log LLM response in parallel (non-blocking)
                        session_log.log_response(
                            step=self.agent_step.steps,
                            content=llm_response.content,
                            thinking=llm_response.thinking,
                            tool_calls=llm_response.tool_calls,
                            usage=llm_response.usage
                        )

                        is_done = False
                        for i, tool_call in enumerate(llm_response.tool_calls):
                            tool_name = tool_call.name
                            tool_args = tool_call.arguments
                            tool_call_id = tool_call.id

                            context.append(ToolCallMessage(
                                content=(llm_response.content or "") if i == 0 else "",
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                tool_input=tool_args
                            ))

                            if tool_name == 'done_tool':
                                action_response = self.registry.execute(tool_name=tool_name, desktop=None, **tool_args)
                                answer = action_response.content
                                context.append(ToolResultMessage(
                                    content=answer or "",
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name
                                ))
                                session_log.log_tool_result(self.agent_step.steps, tool_name, answer or "")
                                is_done = True
                                break
                            else:
                                action_response = self.registry.execute(
                                    tool_name=tool_name, desktop=self.desktop, **tool_args
                                )
                                result_text = action_response.content if action_response.is_success else action_response.error

                                context.append(ToolResultMessage(
                                    content=result_text or "",
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    image=action_response.image
                                ))

                                # Log tool result in parallel (non-blocking)
                                session_log.log_tool_result(self.agent_step.steps, tool_name, result_text or "")

                        context.end_turn()
                        if is_done:
                            break

                if self.telemetry:
                    self.telemetry.capture(AgentTelemetryEvent(
                        query=query,
                        steps=self.agent_step.steps,
                        answer=answer,
                        use_vision=self.use_vision,
                        model=self.llm.model_name,
                        provider=self.llm.provider,
                        is_success=True
                    ))
            self.agent_step.reset()
            session_log.finalize(self.llm.model_name)
            return AgentResult(is_done=True, content=answer)
        except KeyboardInterrupt:
            print("[Agent] Interrupted by user (Ctrl+C).")
            if self.telemetry:
                self.telemetry.flush()
            session_log.finalize(self.llm.model_name)
            return AgentResult(is_done=False, error="Interrupted by user")

    def print_response(self, query: str, start_time=None):
        """Print the response from the agent."""
        response = self.invoke(query, start_time=start_time)
        self.console.print(Markdown(response.content or response.error))
