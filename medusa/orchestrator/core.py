from medusa.orchestrator.tools.service import (click_tool, type_tool, shell_tool, done_tool, multi_select_tool,memory_tool,
shortcut_tool, scroll_tool, drag_tool, move_tool, wait_tool, app_tool, scrape_tool, multi_edit_tool)
from medusa.messages import SystemMessage, HumanMessage, AIMessage, ImageMessage
from medusa.telemetry.views import AgentTelemetryEvent
from medusa.telemetry.tracker import ProductTelemetry
from medusa.orchestrator.views import AgentResult,AgentStep
from medusa.orchestrator.registry.core import Registry
from medusa.orchestrator.watchdog.observer import WatchDog
from medusa.orchestrator.registry.views import ToolResult
from medusa.uia.enums import StructureChangeType
from medusa.orchestrator.desktop.controller import Desktop
from medusa.orchestrator.desktop.state import Browser
from medusa.orchestrator.prompts.generator import Prompt
from medusa.llms.base import BaseChatLLM
from medusa.orchestrator.utils import xml_parser
from medusa.uia import Control
from contextlib import nullcontext
from rich.markdown import Markdown
from rich.console import Console
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter('[%(levelname)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class Agent:
    def __init__(self,instructions:list[str]=[],browser:Browser=Browser.EDGE, llm: BaseChatLLM=None,max_consecutive_failures:int=3,max_steps:int=25,use_vision:bool=False,auto_minimize:bool=False,enable_telemetry:bool=False):
        self.name='Windows Use'
        self.description='An agent that can interact with GUI elements on Windows OS'
        self.registry = Registry([
            click_tool,type_tool, app_tool, shell_tool, done_tool,
            shortcut_tool, scroll_tool, drag_tool, move_tool,memory_tool,
            wait_tool, scrape_tool, multi_select_tool, multi_edit_tool
        ])
        self.instructions=instructions
        self.browser=browser
        self.agent_step=AgentStep(max_steps=max_steps)
        self.max_consecutive_failures=max_consecutive_failures
        self.auto_minimize=auto_minimize
        self.use_vision=use_vision
        self.llm = llm
        self.telemetry=ProductTelemetry() if enable_telemetry else None
        self.watchdog = WatchDog()
        self.desktop = Desktop()
        self.console=Console()

    def invoke(self,query: str)->AgentResult:
        """Invoke the agent with a query."""
        if query.strip()=='':
            return AgentResult(is_done=False, error="Query is empty. Please provide a valid query.")
        try:
            with (self.desktop.auto_minimize() if self.auto_minimize else nullcontext()):
                self.watchdog.set_focus_callback(self.desktop.tree._on_focus_change)
                # self.watchdog.set_structure_callback(self.desktop.tree._on_structure_change) 
                self.watchdog.set_property_callback(self.desktop.tree._on_property_change)
                with self.watchdog:
                    desktop_state = self.desktop.get_state(use_vision=self.use_vision)
                    language=self.desktop.get_default_language()
                    tools_prompt = self.registry.get_tools_prompt()
                    observation="The desktop is ready to operate."
                    system_prompt=Prompt.system_prompt(desktop=self.desktop,
                        browser=self.browser,language=language,instructions=self.instructions,
                        tools_prompt=tools_prompt,max_steps=self.agent_step.max_steps
                    )
                    human_prompt=Prompt.observation_prompt(query=query,agent_step=self.agent_step,
                        tool_result=ToolResult(is_success=True, content=observation), desktop_state=desktop_state
                    )
                    messages=[
                        SystemMessage(content=system_prompt),
                        ImageMessage(content=human_prompt,image=desktop_state.screenshot,mime_type="image/png") 
                            if self.use_vision and desktop_state.screenshot else 
                        HumanMessage(content=human_prompt)
                    ]
                    while self.agent_step.steps < self.agent_step.max_steps:
                        # Increment step counter at the beginning of each iteration
                        self.agent_step.step_increment()
                        
                        logger.info(f"[Agent] 🎯 Step: {self.agent_step.steps}/{self.agent_step.max_steps}")
                        
                        error_messages=[]

                        # Retry logic for LLM failures
                        for consecutive_failures in range(1, self.max_consecutive_failures + 1):
                            try:
                                llm_response = self.llm.invoke(messages+error_messages)
                                agent_data = xml_parser(llm_response)
                                break
                            except ValueError as e:
                                error_messages.clear()
                                error_messages.append(llm_response)
                                error_messages.append(HumanMessage(content=f"Response rejected, invalid response format\nError: {e}\nAdhere to the format specified in <output_contract>"))
                                logger.warning(f"[LLM]: Invalid response format, Retrying attempt {consecutive_failures}/{self.max_consecutive_failures}...")
                                if consecutive_failures == self.max_consecutive_failures:
                                    if self.telemetry:
                                        self.telemetry.capture(AgentTelemetryEvent(
                                            query=query,
                                            error=str(e),
                                            steps=self.agent_step.steps,
                                            max_steps=self.agent_step.max_steps,
                                            use_vision=self.use_vision,
                                            model=self.llm.model_name,
                                            provider=self.llm.provider,
                                            is_success=False
                                        ))
                                    return AgentResult(is_done=False, error=str(e))
                            except Exception as e:
                                logger.error(f"[LLM]: Failed to generate response. Retrying attempt {consecutive_failures}/{self.max_consecutive_failures}...")
                                if consecutive_failures == self.max_consecutive_failures:
                                    if self.telemetry:
                                        self.telemetry.capture(AgentTelemetryEvent(
                                            query=query,
                                            error=str(e),
                                            steps=self.agent_step.steps,
                                            max_steps=self.agent_step.max_steps,
                                            use_vision=self.use_vision,
                                            model=self.llm.model_name,
                                            provider=self.llm.provider,
                                            is_success=False
                                        ))
                                    return AgentResult(is_done=False, error=str(e))

                        logger.info(f"[Agent] 📝 Evaluate: {agent_data.evaluate}")
                        logger.info(f"[Agent] 💭 Thought: {agent_data.thought}")

                        # Remove previous Desktop State Human Message
                        messages.pop()
                        human_prompt = Prompt.previous_observation_prompt(agent_step=self.agent_step, observation=observation)
                        human_message = HumanMessage(content=human_prompt)
                        messages.append(human_message)

                        ai_prompt = Prompt.action_prompt(agent_data=agent_data)
                        ai_message = AIMessage(content=ai_prompt)
                        messages.append(ai_message)

                        action = agent_data.action
                        action_name = action.name
                        params = action.params

                        if action_name.startswith('Done'):
                            action_response = self.registry.execute(tool_name=action_name, desktop=None, **params)
                            answer = action_response.content
                            logger.info(f"[Agent] 📜 Final-Answer: {answer}\n")
                            agent_data.observation = answer
                            human_prompt = Prompt.answer_prompt(agent_data=agent_data, tool_result=action_response)
                            break  # Exit the while loop successfully
                        else:
                            logger.info(f"[Tool] 🔧 Action: {action_name}({', '.join(f'{k}={v}' for k, v in params.items())})")
                            action_response = self.registry.execute(tool_name=action_name, desktop=self.desktop, **params)
                            observation = action_response.content if action_response.is_success else action_response.error
                            logger.info(f"[Tool] 📝 Observation: {observation}\n")
                            agent_data.observation = observation

                            desktop_state = self.desktop.get_state(use_vision=self.use_vision)
                            human_prompt = Prompt.observation_prompt(query=query, agent_step=self.agent_step,
                                tool_result=action_response, desktop_state=desktop_state
                            )
                            human_message = ImageMessage(content=human_prompt, image=desktop_state.screenshot, mime_type="image/png") if self.use_vision and desktop_state.screenshot else HumanMessage(content=human_prompt)
                            messages.append(human_message)
                
                # Check if max steps reached (loop exited without Done action)
                if self.agent_step.steps >= self.agent_step.max_steps:
                    if self.telemetry:
                        self.telemetry.capture(AgentTelemetryEvent(
                            query=query,
                            error="Max steps reached",
                            steps=self.agent_step.steps,
                            max_steps=self.agent_step.max_steps,
                            use_vision=self.use_vision,
                            model=self.llm.model_name,
                            provider=self.llm.provider,
                            is_success=False
                        ))
                    return AgentResult(is_done=False, error="Max steps reached")

                if self.telemetry:
                    self.telemetry.capture(AgentTelemetryEvent(
                        query=query,
                        steps=self.agent_step.steps,
                        max_steps=self.agent_step.max_steps,
                        answer=answer,
                        use_vision=self.use_vision,
                        model=self.llm.model_name,
                        provider=self.llm.provider,
                        is_success=True
                    ))
            self.agent_step.reset()
            return AgentResult(is_done=True,content=answer)
        except KeyboardInterrupt:
            logger.warning("[Agent] ⚠️: Interrupted by user (Ctrl+C).")
            if self.telemetry:
                self.telemetry.flush()
            return AgentResult(is_done=False, error="Interrupted by user")
        
    def print_response(self,query: str):
        """Print the response from the agent."""
        response=self.invoke(query)
        self.console.print(Markdown(response.content or response.error))