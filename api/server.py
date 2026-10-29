"""
HalluGuard AI — Lightweight FastAPI Server.

Exposes the core analysis pipeline over HTTP so the VSCode extension
(and any other client) can call ``POST /analyze``.

Start with::

    uvicorn api.server:app --host 127.0.0.1 --port 7432

CORS is **disabled by default** (the VSCode extension talks to the server from
Node, which is not subject to CORS).  A browser client must be allowed
explicitly with ``HALLUGUARD_CORS_ORIGINS="https://a.example,https://b.example"``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.pipeline import SUPPORTED_LANGUAGES, analyze
from core.rwkv_engine import model_loader

logger = logging.getLogger(__name__)

# ── FastAPI application ────────────────────────────────────────────
app = FastAPI(
    title="HalluGuard AI",
    version="1.0.0",
    description="Detect, explain, and correct hallucinations in AI-generated code.",
)

_origins = [
    o.strip()
    for o in os.environ.get("HALLUGUARD_CORS_ORIGINS", "").split(",")
    if o.strip() and o.strip() != "*"
]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


# ── Request / Response models ─────────────────────────────────────
class AnalyzeRequest(BaseModel):
    """Payload sent by the VSCode extension or any client."""
    code: str = Field(..., description="Source code to analyze.")
    language: str = Field("python", description="python | javascript | typescript")
    file_name: str | None = Field(None, description="Optional file name.")
    project_root: str | None = Field(
        None, description="Directory used to resolve project-local modules."
    )
    offline: bool | None = Field(None, description="Never query PyPI/npm.")


class HallucinationItem(BaseModel):
    line: int
    column: int = 0
    type: str
    token: str
    explanation: str
    suggestion: str
    severity: str


class SuggestionItem(BaseModel):
    token: str
    original_type: str | None = None
    suggestion: str | None = None
    explanation: str | None = None
    confidence: str | None = None


class AnalyzeResponse(BaseModel):
    """JSON payload returned to the client."""
    file: str
    risk_score: int
    risk_level: str
    severity: str
    confidence: str
    hallucinations: list[HallucinationItem]
    suggestions: list[SuggestionItem]
    unverified: list[str]
    notes: list[str]


class HealthResponse(BaseModel):
    status: str
    rwkv_available: bool
    rwkv_model_file_found: bool
    rwkv_package_installed: bool
    rwkv_loaded: bool
    version: str


# ── Endpoints ──────────────────────────────────────────────────────
# Plain ``def`` endpoints run in FastAPI's thread pool: the analysis does
# blocking I/O (registry lookups, subprocesses, model inference) and must not
# stall the event loop.
@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_code(req: AnalyzeRequest) -> dict[str, Any]:
    """Analyze a code snippet for hallucinations."""
    if req.language.lower() not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported language '{req.language}'. "
                "Choose from: python, javascript, typescript."
            ),
        )
    report = analyze(
        req.code,
        language=req.language,
        file_name=req.file_name,
        project_root=req.project_root,
        offline=req.offline,
    )
    return report.to_dict()


@app.get("/health", response_model=HealthResponse)
def health_check() -> dict[str, Any]:
    """Server health and detailed RWKV status."""
    st = model_loader.status()
    return {
        "status": "ok",
        "rwkv_available": model_loader.is_available(),
        "rwkv_model_file_found": st["model_file_found"],
        "rwkv_package_installed": st["package_installed"],
        "rwkv_loaded": st["loaded"],
        "version": "1.0.0",
    }
