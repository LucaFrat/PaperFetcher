"""Two-stage paper picker: sentence-transformers shortlist → Claude rerank → top 1."""
from __future__ import annotations

import logging

import numpy as np

from . import claude_cli
from .fetch import Paper

logger = logging.getLogger(__name__)


def _embed(model_name: str, texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def _shortlist(papers: list[Paper], interests_body: str, model_name: str,
               size: int) -> list[Paper]:
    if len(papers) <= size:
        return papers
    docs = [interests_body] + [f"{p.title}\n\n{p.abstract}" for p in papers]
    embs = _embed(model_name, docs)
    interest_vec = embs[0]
    paper_vecs = embs[1:]
    scores = paper_vecs @ interest_vec
    order = np.argsort(-scores)[:size]
    short = [papers[i] for i in order]
    logger.info("embedding shortlist: %d -> %d (top score %.3f, cutoff %.3f)",
                len(papers), len(short), float(scores[order[0]]),
                float(scores[order[-1]]))
    return short


def _rerank_with_claude(papers: list[Paper], interests_body: str) -> Paper | None:
    bullets = "\n\n".join(
        f"[{i}] id={p.id}\nTitle: {p.title}\nAbstract: {p.abstract}"
        for i, p in enumerate(papers)
    )
    prompt = (
        "You are helping pick the SINGLE most relevant arXiv paper for a "
        "researcher with the interests below. Read the candidate list and "
        "return the index of the best paper plus a one-sentence reason.\n\n"
        f"=== Researcher interests ===\n{interests_body}\n\n"
        f"=== Candidates ===\n{bullets}"
    )
    schema = {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["index", "reason"],
        "additionalProperties": False,
    }
    try:
        answer = claude_cli.json_obj(prompt, schema=schema, label="rerank")
    except claude_cli.ClaudeCLIError as e:
        logger.warning("claude rerank failed: %s — falling back to embedding top-1", e)
        return None
    idx = int(answer["index"])
    if not 0 <= idx < len(papers):
        logger.warning("claude returned out-of-range index %d", idx)
        return None
    logger.info("claude rerank picked [%d] %s — %s",
                idx, papers[idx].id, answer.get("reason", ""))
    return papers[idx]


def pick_top(papers: list[Paper], *, interests_body: str,
             embedding_model: str, shortlist_size: int) -> Paper | None:
    if not papers:
        return None
    short = _shortlist(papers, interests_body, embedding_model, shortlist_size)
    return _rerank_with_claude(short, interests_body) or short[0]
