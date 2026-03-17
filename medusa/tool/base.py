import asyncio
import inspect
from pydantic import BaseModel
from typing import Any

class Tool:
    """Base tool class with decorator pattern for registering tool functions."""

    def __init__(self, name: str|None=None, description: str|None=None, args_schema:BaseModel|None=None):
        self.name = name
        self.description = description
        self.tool_id = None
        self.model = args_schema
        self.args_schema = self.preprocess_schema(args_schema)
        self.function = None

    def preprocess_schema(self, args_schema:BaseModel):
        """Generate JSON Schema from pydantic model."""
        schema = args_schema.model_json_schema()
        properties = {k:{term:content for term,content in v.items() if term not in ['title']} for k,v in schema.get('properties').items() if k not in ['title']}
        required = [name for name, field in args_schema.model_fields.items() if field.is_required()]
        return {
            'type': 'object',
            'properties': properties,
            'required': required
        }

    def __call__(self, function):
        if self.name is None:
            self.name = function.__name__
        if self.description is None:
            self.description = function.__doc__
        self.tool_id = function.__name__
        self.function = function
        return self

    async def invoke(self, *args, **kwargs):
        if inspect.iscoroutinefunction(self.function):
            return await self.function(*args, **kwargs)
        return await asyncio.to_thread(self.function, *args, **kwargs)
