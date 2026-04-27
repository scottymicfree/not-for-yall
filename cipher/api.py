"""
Cipher Intelligence FastAPI Router
Endpoints: detect, list, search, stats
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from .cipher_db import cipher_db
from .detector import detector

router = APIRouter(prefix="/api/cipher", tags=["cipher"])


class DetectRequest(BaseModel):
    text: str = Field(..., min_length=2, max_length=65536, description="Ciphertext to analyze")
    top_n: int = Field(default=5, ge=1, le=20)


@router.post("/detect")
async def detect_cipher(req: DetectRequest):
    """Analyze ciphertext and return ranked cipher matches."""
    result = detector.detect(req.text, top_n=req.top_n)
    return result.to_dict()


@router.get("/list")
async def list_ciphers(
    category: Optional[str] = Query(None),
    era: Optional[str] = Query(None),
    frequency_detectable: Optional[bool] = Query(None),
    limit: int = Query(default=78, ge=1, le=78),
):
    """List all ciphers with optional filters."""
    ciphers = cipher_db.all()
    if category:
        ciphers = [c for c in ciphers if c.category.lower() == category.lower()]
    if era:
        ciphers = [c for c in ciphers if c.era.lower() == era.lower()]
    if frequency_detectable is not None:
        ciphers = [c for c in ciphers if c.frequency_flag == frequency_detectable]
    return {
        "total": len(ciphers),
        "ciphers": [c.to_dict() for c in ciphers[:limit]],
    }


@router.get("/stats")
async def cipher_stats():
    """Return database statistics."""
    return cipher_db.stats()


@router.get("/search")
async def search_ciphers(q: str = Query(..., min_length=1)):
    """Search ciphers by name, tags, description."""
    results = cipher_db.search(q)
    return {"query": q, "total": len(results), "results": [c.to_dict() for c in results]}


@router.get("/ioc")
async def ciphers_by_ioc(ioc: float = Query(..., ge=0.0, le=1.0)):
    """Return ciphers whose IoC range matches the given value."""
    results = cipher_db.by_ioc_range(ioc)
    return {"ioc": ioc, "total": len(results), "matches": [c.to_dict() for c in results]}


@router.get("/{cipher_id}")
async def get_cipher(cipher_id: str):
    """Get a single cipher entry by ID (e.g. C001)."""
    entry = cipher_db.get(cipher_id)
    if not entry:
        # Try by name
        entry = cipher_db.get_by_name(cipher_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Cipher '{cipher_id}' not found")
    return entry.to_dict()