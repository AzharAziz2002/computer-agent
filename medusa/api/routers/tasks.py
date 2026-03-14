import os
import asyncio
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from medusa.orchestrator.core import Agent
from medusa.orchestrator.desktop.state import Browser
from medusa.llms.anthropic import ChatAnthropic
from medusa.api.models import StartTaskRequest, StartTaskResponse, AgentStepModel, AgentActionModel, TaskUpdateFrame
from medusa.api.state import store

load_dotenv()

router = APIRouter()


def _run_agent(task_id: str, query: str, model: str, loop: asyncio.AbstractEventLoop) -> None:
    """Runs Agent.invoke() in a thread pool — notifies WebSocket clients via asyncio queues."""
    task = store.get(task_id)
    if not task:
        return

    task.status = "running"

    def step_callback(raw: dict) -> None:
        step_num = len(task.steps) + 1
        action_raw = raw.get("action")
        step = AgentStepModel(
            id=str(uuid4()),
            stepNumber=step_num,
            action=AgentActionModel(**action_raw) if action_raw else None,
            observation=raw.get("observation"),
            isError=raw.get("isError", False),
        )
        task.steps.append(step.model_dump())
        frame = TaskUpdateFrame(task_id=task_id, status="running", step=step).model_dump()
        for q in task.queues:
            loop.call_soon_threadsafe(q.put_nowait, frame)

    try:
        llm = ChatAnthropic(
            model=model,
            api_key=os.getenv("CLAUDE_API_KEY"),
            thinking_budget=-1,
        )
        agent = Agent(llm=llm, auto_minimize=True)
        result = agent.invoke(
            query,
            start_time=datetime.now(),
            step_callback=step_callback,
            stop_event=task.stop_event,
        )

        if result.is_done:
            task.status = "done"
            task.result = result.content
        else:
            task.status = "failed"
            task.error = result.error

    except Exception as e:
        task.status = "failed"
        task.error = str(e)

    finally:
        final_frame = TaskUpdateFrame(
            task_id=task_id,
            status=task.status,
            result=task.result,
            error=task.error,
        ).model_dump()
        for q in task.queues:
            loop.call_soon_threadsafe(q.put_nowait, final_frame)
            # Sentinel so WS handler knows to close
            loop.call_soon_threadsafe(q.put_nowait, None)


@router.post("/api/tasks", response_model=StartTaskResponse)
async def start_task(req: StartTaskRequest):
    task_id = str(uuid4())
    store.create(task_id, req.query)
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run_agent, task_id, req.query, req.model, loop)
    return StartTaskResponse(task_id=task_id)


@router.delete("/api/tasks/{task_id}", status_code=204)
async def stop_task(task_id: str):
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.stop_event.set()


@router.websocket("/api/ws/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    await websocket.accept()

    task = store.get(task_id)
    if not task:
        await websocket.close(code=4004)
        return

    queue: asyncio.Queue = asyncio.Queue()
    task.queues.append(queue)

    try:
        while True:
            frame = await queue.get()
            if frame is None:
                break
            await websocket.send_json(frame)
    except WebSocketDisconnect:
        pass
    finally:
        task.queues.remove(queue)
        await websocket.close()
