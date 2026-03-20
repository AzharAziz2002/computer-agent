import os
import asyncio
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from medusa.orchestrator.core import Agent
from medusa.llms.anthropic import ChatAnthropic
from medusa.api.models import StartTaskRequest, StartTaskResponse, AgentStepModel, AgentActionModel, TaskUpdateFrame
from medusa.api.state import store

load_dotenv()

router = APIRouter()


async def _run_agent(task_id: str, query: str, model: str) -> None:
    """Runs Agent.invoke() as an async task — notifies WebSocket clients via asyncio queues."""
    task = store.get(task_id)
    if not task:
        return

    task.status = "running"
    loop = asyncio.get_event_loop()

    def delta_callback(delta: str) -> None:
        """Called from LLM worker thread for each streamed text chunk."""
        frame = TaskUpdateFrame(task_id=task_id, type="delta", status="running", delta=delta).model_dump()
        for q in list(task.queues):
            loop.call_soon_threadsafe(q.put_nowait, frame)

    def step_callback(raw: dict) -> None:
        step_num = len(task.steps) + 1
        action_raw = raw.get("action")
        step = AgentStepModel(
            id=str(uuid4()),
            stepNumber=step_num,
            thought=raw.get("thought"),
            action=AgentActionModel(**action_raw) if action_raw else None,
            observation=raw.get("observation"),
            isError=raw.get("isError", False),
        )
        task.steps.append(step.model_dump())
        frame = TaskUpdateFrame(task_id=task_id, type="step", status="running", step=step).model_dump()
        for q in task.queues:
            q.put_nowait(frame)

    try:
        llm = ChatAnthropic(
            model=model,
            api_key=os.getenv("CLAUDE_API_KEY"),
            thinking_budget=-1,
        )
        agent = Agent(llm=llm, auto_minimize=False)
        result = await agent.invoke(
            query,
            start_time=datetime.now(),
            step_callback=step_callback,
            stop_event=task.stop_event,
            delta_callback=delta_callback,
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
            type="done",
            status=task.status,
            result=task.result,
            error=task.error,
        ).model_dump()
        for q in task.queues:
            q.put_nowait(final_frame)
            # Sentinel so WS handler knows to close
            q.put_nowait(None)


@router.post("/api/tasks", response_model=StartTaskResponse)
async def start_task(req: StartTaskRequest):
    task_id = str(uuid4())
    store.create(task_id, req.query)
    asyncio.create_task(_run_agent(task_id, req.query, req.model))
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
