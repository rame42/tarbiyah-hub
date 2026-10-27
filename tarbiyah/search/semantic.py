"""Optional semantic (embedding) search, fused with keyword search.

Provider: Voyage AI (multilingual embeddings, Arabic + English; free tier available).
Enabled only when VOYAGE_API_KEY is set. Without it, retrieval uses bilingual keyword
search + glossary expansion (+ Claude query expansion when available).

Vectors are stored in the `embeddings` table and searched with brute-force cosine
similarity in NumPy, which is fast enough for a few hundred thousand passages on a
laptop. Upgrade path: a vector index (sqlite-vec, pgvector) behind the same functions.
"""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_config
from ..http import http
from ..models import Chunk, Embedding

MODEL = "voyage-3.5"
EmbedFn = Callable[[list[str], str], list[list[float]]]
_override: EmbedFn | None = None
_cache: dict[str, object] = {"n": -1}
_lock = threading.Lock()


def set_embedder(fn: EmbedFn | None, model: str | None = None) -> None:
    """Tests inject a local embedder; production uses Voyage."""
    global _override, MODEL
    _override = fn
    if model:
        MODEL = model
    _cache["n"] = -1


def available() -> bool:
    return _override is not None or bool(get_config().voyage_api_key)


def embed(texts: list[str], input_type: str) -> list[list[float]]:
    if _override is not None:
        return _override(texts, input_type)
    key = get_config().voyage_api_key
    if not key:
        raise RuntimeError("VOYAGE_API_KEY not set")
    import json

    res = http().fetch("https://api.voyageai.com/v1/embeddings", method="POST", check_robots=False,
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       data=json.dumps({"input": texts, "model": MODEL, "input_type": input_type}), timeout=120)
    data = res.json()["data"]
    return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]


def embed_pending(session: Session, limit: int = 256, batch: int = 64) -> int:
    done = select(Embedding.chunk_id).where(Embedding.model == MODEL)
    rows = session.execute(select(Chunk).where(Chunk.id.not_in(done)).order_by(Chunk.id).limit(limit)).scalars().all()
    n = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = embed([c.text[:6000] for c in part], "document")
        for c, v in zip(part, vecs):
            arr = np.asarray(v, dtype=np.float32)
            arr /= (np.linalg.norm(arr) or 1.0)
            session.add(Embedding(chunk_id=c.id, model=MODEL, dim=arr.shape[0], vector=arr.tobytes()))
            n += 1
        session.commit()
    _cache["n"] = -1
    return n


def _matrix(session: Session) -> tuple[np.ndarray, np.ndarray]:
    with _lock:
        n = session.execute(select(func.count()).select_from(Embedding).where(Embedding.model == MODEL)).scalar() or 0
        if _cache.get("n") != n:
            rows = session.execute(select(Embedding.chunk_id, Embedding.vector).where(Embedding.model == MODEL)).all()
            ids = np.array([r[0] for r in rows], dtype=np.int64)
            mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1), np.float32)
            _cache.update({"n": n, "ids": ids, "mat": mat})
        return _cache["ids"], _cache["mat"]  # type: ignore[return-value]


def semantic_chunks(session: Session, query: str, k: int = 20) -> list[tuple[int, float]]:
    if not available():
        return []
    ids, mat = _matrix(session)
    if len(ids) == 0:
        return []
    q = np.asarray(embed([query], "query")[0], dtype=np.float32)
    q /= (np.linalg.norm(q) or 1.0)
    scores = mat @ q
    top = np.argsort(-scores)[:k]
    return [(int(ids[i]), float(scores[i])) for i in top]


def fuse(keyword: list[int], semantic: list[int], k: int = 60) -> list[int]:
    """Reciprocal-rank fusion of two ranked id lists."""
    score: dict[int, float] = {}
    for lst in (keyword, semantic):
        for rank, i in enumerate(lst):
            score[i] = score.get(i, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=lambda i: score[i], reverse=True)
