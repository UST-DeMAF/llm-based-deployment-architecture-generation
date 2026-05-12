import os
import requests
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

import rag  # RAG logic (Chroma + Ollama)
#import rag_single as rag

# raw generate API
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")


class Question(BaseModel):
    question: str


from typing import Optional

class RAGQuestion(BaseModel):
    question: str
    case: Optional[str] = None
    platform: Optional[str] = None
    target_resource: Optional[str] = None
    output_format: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No runtime ingestion here.
    # Chroma collections are created offline via ingest_rules.py (kb_core).
    kb_name = os.getenv("KB_COLLECTION", "kb_core")
    top_k = os.getenv("TOP_K", "8")
    debug = os.getenv("DEBUG_RETRIEVAL", "0")
    print(f"[API] RAG startup: using KB_COLLECTION={kb_name}, TOP_K={top_k}, DEBUG_RETRIEVAL={debug}")
    yield
    # shutdown side (optional)


app = FastAPI(lifespan=lifespan)


@app.post("/ask")
def ask_question(data: Question):
    payload = {
        "model": "llama3",
        "prompt": data.question,
        "stream": False,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    return {"answer": result.get("response", "")}


@app.post("/rag")
def rag_question(data: RAGQuestion):
    ans = rag.answer(
        data.question,
        case=data.case,
        platform=data.platform,
        target_resource=data.target_resource,
        output_format=data.output_format,
    )
    return {"answer": ans}
