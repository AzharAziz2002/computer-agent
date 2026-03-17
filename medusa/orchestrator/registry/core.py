from medusa.orchestrator.registry.views import ToolResult
from medusa.orchestrator.desktop.controller import Desktop
from medusa.tool import Tool
from textwrap import dedent
import json

class Registry:
    """Tool registry for managing and executing tools."""

    def __init__(self,tools:list[Tool]=[]):
        self.tools=tools
        self.tools_registry=self._build_registry()

    def _build_registry(self):
        registry = {}
        for tool in self.tools:
            registry[tool.tool_id] = tool
            registry[tool.name] = tool
        return registry

    def get_tools_schema(self) -> list[dict]:
        """Returns provider-agnostic tool schemas for native tool calling."""
        return [
            {
                'name': tool.tool_id,
                'description': tool.description,
                'parameters': tool.args_schema
            }
            for tool in self.tools
        ]

    def get_tools_prompt(self) -> str:
        """Returns formatted text prompt with all tool descriptions (legacy)."""
        tools_prompt = [self._tool_prompt(tool.name) for tool in self.tools]
        return '\n\n'.join(tools_prompt)

    def _tool_prompt(self, tool_name: str) -> str:
        tool = self.tools_registry.get(tool_name)
        if tool is None:
            return f"Tool '{tool_name}' not found."
        return dedent(f"""
        Tool Name: {tool.name}
        Tool Description: {tool.description}
        Tool Schema: {json.dumps(tool.args_schema,indent=4)}
        """)

    async def execute(self, tool_name: str, desktop: Desktop|None=None, browser=None, **kwargs) -> ToolResult:
        """Execute a tool by name (supports both tool_id and display name)."""
        tool = self.tools_registry.get(tool_name)
        if tool is None:
            return ToolResult(is_success=False, error=f"Tool '{tool_name}' not found.")
        try:
            args=tool.model.model_validate(kwargs)
            result = await tool.invoke(**({'desktop': desktop, 'browser': browser} | args.model_dump()))
            if isinstance(result, ToolResult):
                return result
            return ToolResult(is_success=True, content=result)
        except Exception as error:
            return ToolResult(is_success=False, error=str(error))
