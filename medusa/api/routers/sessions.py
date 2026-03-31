from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from medusa.sessions import session_store

router = APIRouter()


class RenameSessionRequest(BaseModel):
    title: str


@router.get("/api/sessions")
async def list_sessions():
    return session_store.list_sessions()


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    meta = session_store.get(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")
    transcript = session_store.load_transcript(session_id)
    return {"session": meta, "transcript": transcript}


@router.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, body: RenameSessionRequest):
    meta = session_store.get(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    session_store.update(session_id, title=title)
    return session_store.get(session_id)


@router.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    session_store.delete(session_id)
