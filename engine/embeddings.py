"""Small, offline embeddings for clause retrieval.

The regulation text is embedded once and stored next to the pack clauses; a
sentence is embedded at check time and the nearest clauses are retrieved. The
default model is deliberately local and deterministic: a signed feature-hash of
word unigrams, bigrams and character trigrams, L2-normalised into 768 dimensions
(the pgvector column width). It costs nothing, works without a key, and cannot
send client copy to a third party.

On Postgres the vectors live in a `vector(768)` column and are ranked by cosine
distance inside the database (pgvector). SQLite stores the same vector as JSON
and ranks it in Python, so tests and the local demo exercise identical logic.

`CANONRY_EMBEDDING_MODEL=gemini` is an opt-in upgrade: when a Gemini key is
configured, `embed()` calls the embedding API and the vectors are stored through
the same column. Nothing in the compliance verdict depends on the model: the
deterministic triggers decide, retrieval only finds the clause to cite.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

DIM = 768
LOCAL_MODEL = "canonry-hash-ngram@1"
GEMINI_MODEL = "text-embedding-004"


def model_name() -> str:
    requested = (os.environ.get("CANONRY_EMBEDDING_MODEL") or "").strip().lower()
    if requested == "gemini" and (os.environ.get("GEMINI_API_KEY") or "").strip():
        return GEMINI_MODEL
    return LOCAL_MODEL


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = list(words)
    out += [f"{a}_{b}" for a, b in zip(words, words[1:])]
    for word in words:
        padded = f"#{word}#"
        for i in range(len(padded) - 2):
            out.append(padded[i:i + 3])
    return out


def local_embed(text: str) -> List[float]:
    vec = [0.0] * DIM
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        # a rare token carries more signal than a common stop word
        weight = 1.0 if len(token) > 3 else 0.5
        vec[bucket] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def _gemini_embed(texts: Sequence[str]) -> Optional[List[List[float]]]:
    """Batch embedding through the same free Gemini key the gateway uses."""
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import httpx

        model = os.environ.get("CANONRY_EMBEDDING_MODEL_NAME") or GEMINI_MODEL
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
        body = {
            "requests": [
                {"model": f"models/{model}", "content": {"parts": [{"text": t[:8000]}]},
                 "taskType": "RETRIEVAL_DOCUMENT"}
                for t in texts
            ]
        }
        with httpx.Client(timeout=12) as client:
            resp = client.post(url, params={"key": key}, json=body)
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("embeddings", []):
            values = [float(v) for v in item.get("values", [])]
            if len(values) != DIM:
                return None
            out.append(values)
        return out if len(out) == len(texts) else None
    except Exception:
        return None  # retrieval falls back to the local model, never a failed check


def embed_many(texts: Sequence[str]) -> List[List[float]]:
    if model_name() != LOCAL_MODEL:
        vectors = _gemini_embed(texts)
        if vectors:
            return vectors
    return [local_embed(t) for t in texts]


def embed(text: str) -> List[float]:
    return embed_many([text])[0]


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def cache_key(text: str, model: Optional[str] = None) -> str:
    return hashlib.sha256(((model or model_name()) + "\x00" + text).encode("utf-8")).hexdigest()


def cached_embed(conn, text: str) -> List[float]:
    """Embedding cache: a clause re-seed or a repeat check costs no API call."""
    model = model_name()
    key = cache_key(text, model)
    row = conn.execute(
        "SELECT vector_json FROM embedding_cache WHERE hash = ? AND model = ?", (key, model)).fetchone()
    if row:
        try:
            vec = json.loads(row["vector_json"])
            if isinstance(vec, list) and len(vec) == DIM:
                return [float(v) for v in vec]
        except (TypeError, ValueError):
            pass
    vec = embed(text)
    conn.execute(
        "INSERT INTO embedding_cache (hash, model, dim, vector_json, created_at) VALUES (?,?,?,?,?)",
        (key, model, DIM, json.dumps(vec), __import__("db")._now()),
    )
    return vec


def top_clauses(conn, workspace_id: str, query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Nearest active clauses for one sentence, workspace packs only."""
    from db import dialect  # local import keeps module import order simple

    model = model_name()
    query_vec = cached_embed(conn, query)
    packs = [r["pack_id"] for r in conn.execute(
        "SELECT pack_id FROM workspace_packs WHERE workspace_id = ? AND active = 1",
        (workspace_id,)).fetchall()]
    if not packs:
        return []
    placeholders = ",".join("?" for _ in packs)
    if dialect() == "postgres":
        sql = (
            "SELECT id, version, pack_id, source, ref, heading, text, url, severity, "
            "triggers_json, requirements_json, exemptions_json, "
            "1 - (embedding <=> ?::vector) AS score "
            "FROM pack_clauses WHERE active = 1 AND embedding IS NOT NULL "
            f"AND pack_id IN ({placeholders}) ORDER BY embedding <=> ?::vector LIMIT ?"
        )
        try:
            rows = conn.execute(sql, (vector_literal(query_vec), *packs,
                                      vector_literal(query_vec), limit)).fetchall()
        except Exception:
            rows = []
    else:
        sql = (
            "SELECT id, version, pack_id, source, ref, heading, text, url, severity, "
            "triggers_json, requirements_json, exemptions_json, embedding_json "
            f"FROM pack_clauses WHERE active = 1 AND pack_id IN ({placeholders})"
        )
        rows = conn.execute(sql, tuple(packs)).fetchall()
    scored = []
    for row in rows:
        data = dict(row)
        if "score" in data and data["score"] is not None:
            score = float(data["score"])
        else:
            try:
                vec = json.loads(data.pop("embedding_json", "[]"))
            except (TypeError, ValueError):
                continue
            score = cosine(query_vec, [float(v) for v in vec])
        data["embedding_model"] = model
        data["score"] = round(score, 4)
        scored.append(data)
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:limit]


def status(conn) -> Dict[str, Any]:
    try:
        row = conn.execute("SELECT COUNT(*) c FROM pack_clauses WHERE active = 1").fetchone()
        cached = conn.execute("SELECT COUNT(*) c FROM embedding_cache").fetchone()
        return {"model": model_name(), "dimensions": DIM, "clauses": row["c"] if row else 0,
                "cached_embeddings": cached["c"] if cached else 0,
                "provider": "gemini" if model_name() != LOCAL_MODEL else "local"}
    except Exception:
        return {"model": model_name(), "dimensions": DIM, "clauses": 0, "cached_embeddings": 0,
                "provider": "local"}
