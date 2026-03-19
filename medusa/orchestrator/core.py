from medusa.orchestrator.tools.service import desktop, shell, done, app, browser
from medusa.orchestrator.browser.controller import BrowserController
from medusa.orchestrator.browser.config import BrowserConfig
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
import traceback
import asyncio

class Agent:
    def __init__(self, instructions: list[str]=[], browser_choice: Browser=Browser.EDGE, llm: BaseChatLLM=None, max_consecutive_failures: int=3, use_vision: bool=False, auto_minimize: bool=False, enable_telemetry: bool=False):
        self.name = 'Medusa'
        self.description = 'An agent that can interact with GUI elements on Windows OS'
        self.registry = Registry([
        browser
        ])
        self.browser_controller = BrowserController(BrowserConfig())
        self.instructions = instructions
        self.browser = browser_choice
        self.agent_step = AgentStep()
        self.max_consecutive_failures = max_consecutive_failures
        self.auto_minimize = auto_minimize
        self.use_vision = use_vision
        self.llm = llm
        self.telemetry = ProductTelemetry() if enable_telemetry else None
        self.watchdog = WatchDog()
        self.desktop = Desktop()
        self.console = Console()

    async def invoke(self, query: str, start_time=None, step_callback=None, stop_event=None) -> AgentResult:
        """Invoke the agent with a query."""
        if query.strip() == '':
            return AgentResult(is_done=False, error="Query is empty. Please provide a valid query.")
        session_log = SessionLogger(
            query=query,
            model_name=self.llm.model_name if self.llm else "unknown",
            start_time=start_time,
        )
        answer = None
        error = None
        try:
            with (self.desktop.auto_minimize() if self.auto_minimize else nullcontext()):
                self.watchdog.set_focus_callback(self.desktop.tree._on_focus_change)
                self.watchdog.set_property_callback(self.desktop.tree._on_property_change)
                with self.watchdog:
                    language = self.desktop.get_default_language()
                    tools_schema = self.registry.get_tools_schema()
                    system_prompt = Prompt.system_prompt(
                        desktop=self.desktop, browser=self.browser,
                        language=language, instructions=self.instructions
                    )
                    context = ContextManager(block_limit=3, screenshot_limit=2, cache_query=False)
                    context.append(SystemMessage(content=system_prompt))
                    context.append(HumanMessage(content=query))
                    session_log.mark_ready()

                    while True:
                        self.agent_step.step_increment()
                        print(f"[DEBUG] === Step {self.agent_step.steps} ===")

                        # Retry logic for LLM failures
                        llm_response = None
                        for consecutive_failures in range(1, self.max_consecutive_failures + 1):
                            try:
                                print(f"[DEBUG] Calling LLM (attempt {consecutive_failures})...")
                                llm_response = await asyncio.to_thread(
                                    self.llm.invoke, context.messages, tools=tools_schema
                                )
                                print(f"[DEBUG] LLM returned. tool_calls={len(llm_response.tool_calls) if llm_response.tool_calls else 0}, content_len={len(llm_response.content) if llm_response.content else 0}")
                                break
                            except Exception as e:
                                print(f"[DEBUG] LLM attempt {consecutive_failures} failed: {e}")
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
                                    error = str(e)
                                    raise  # Let finally handle cleanup

                        if not llm_response or not llm_response.tool_calls:
                            answer = llm_response.content if llm_response else ""
                            print(f"[DEBUG] Loop EXIT: no tool_calls. answer='{answer[:200] if answer else ''}'")
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
                        # Drop screenshot from batches that include a shell call
                        tool_calls = llm_response.tool_calls
                        has_shell = any(tc.name == 'shell' for tc in tool_calls)
                        if has_shell:
                            tool_calls = [tc for tc in tool_calls if tc.name != 'desktop' or tc.arguments.get('action') != 'screenshot']
                        for i, tool_call in enumerate(tool_calls):
                            tool_name = tool_call.name
                            tool_args = tool_call.arguments
                            tool_call_id = tool_call.id

                            context.append(ToolCallMessage(
                                content=(llm_response.content or "") if i == 0 else "",
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                tool_input=tool_args
                            ))

                            print(f"[DEBUG] Tool call: {tool_name}({tool_args})")
                            if tool_name == 'done':
                                action_response = await self.registry.execute(tool_name=tool_name, desktop=None, browser=None, **tool_args)
                                answer = action_response.content
                                print(f"[DEBUG] Loop EXIT: done tool called. answer='{answer[:200] if answer else ''}'  is_success={action_response.is_success}")
                                context.append(ToolResultMessage(
                                    content=answer or "",
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name
                                ))
                                session_log.log_tool_result(self.agent_step.steps, tool_name, answer or "")
                                is_done = True
                                break
                            else:
                                action_response = await self.registry.execute(
                                    tool_name=tool_name, desktop=self.desktop,
                                    browser=self.browser_controller, **tool_args
                                )
                                result_text = action_response.content if action_response.is_success else action_response.error
                                print(f"[DEBUG] Tool result: is_success={action_response.is_success}, text='{(result_text or '')[:150]}'")
                                if not action_response.is_success:
                                    print(f"[DEBUG] Tool ERROR: {action_response.error}")

                                context.append(ToolResultMessage(
                                    content=result_text or "",
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    image=action_response.image
                                ))

                                # Log tool result in parallel (non-blocking)
                                session_log.log_tool_result(self.agent_step.steps, tool_name, result_text or "")

                                # Stream step to API clients
                                if stop_event and stop_event.is_set():
                                    raise RuntimeError("stopped")
                                if step_callback:
                                    step_callback({
                                        "stepNumber": self.agent_step.steps,
                                        "thought": (llm_response.content or None) if i == 0 else None,
                                        "action": {"name": tool_name, "params": tool_args},
                                        "observation": result_text or "",
                                        "isError": not action_response.is_success
                                    })

                        context.end_turn()
                        if is_done:
                            print("[DEBUG] Loop EXIT: is_done=True after done tool")
                            break
                        print(f"[DEBUG] End of step {self.agent_step.steps}, looping...")

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
            return AgentResult(is_done=True, content=answer)
        except KeyboardInterrupt:
            print("[Agent] Interrupted by user (Ctrl+C).")
            error = "Interrupted by user"
            return AgentResult(is_done=False, error=error)
        except Exception as e:
            error = str(e)
            print(f"[Agent] Exception: {error}")
            traceback.print_exc()
            return AgentResult(is_done=False, error=error)
        finally:
            print(f"[DEBUG] === FINALLY cleanup === error={error}")
            self.agent_step.reset()
            print("[DEBUG] Finalizing session log...")
            session_log.finalize(self.llm.model_name)
            print("[DEBUG] Session log finalized.")
            if self.telemetry and error:
                self.telemetry.flush()

    def print_response(self, query: str, start_time=None):
        """Print the response from the agent."""
        response = asyncio.run(self.invoke(query, start_time=start_time))
        self.console.print(Markdown(response.content or response.error))
