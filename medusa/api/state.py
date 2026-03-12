import asyncio
import threading
from dataclasses import dataclass, field


@dataclass
class TaskState:
    task_id: str
    query: str
    status: str = "queued"          # queued | running | done | failed
    steps: list[dict] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    queues: list[asyncio.Queue] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event)


class TaskStore:
    def __init__(self):
        self._tasks: dict[str, TaskState] = {}

    def create(self, task_id: str, query: str) -> TaskState:
        task = TaskState(task_id=task_id, query=query)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> TaskState | None:
        return self._tasks.get(task_id)

    def all(self) -> list[TaskState]:
        return list(self._tasks.values())


# Singleton — imported by routers
store = TaskStore()
