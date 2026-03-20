from pydantic import BaseModel


class StartTaskRequest(BaseModel):
    query: str
    model: str = "claude-sonnet-4-6"


class StartTaskResponse(BaseModel):
    task_id: str


class AgentActionModel(BaseModel):
    name: str
    params: dict


class AgentStepModel(BaseModel):
    id: str
    stepNumber: int
    thought: str | None = None
    action: AgentActionModel | None = None
    observation: str | None = None
    isError: bool = False


class TaskUpdateFrame(BaseModel):
    task_id: str
    type: str = "step"   # "delta" | "step" | "done" | "error"
    status: str          # "running" | "done" | "failed"
    delta: str | None = None
    step: AgentStepModel | None = None
    result: str | None = None
    error: str | None = None
