from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict
from backend.agent.agent import run_agent

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []


@router.post("/chat")
def chat_with_agent(req: ChatRequest):
    return run_agent(req.message, req.history)
