"""PDF download, pymupdf text extraction, and Claude-written digest paragraph."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz  # pymupdf
import requests

from . import claude_cli
from .fetch import Paper

logger = logging.getLogger(__name__)

_UA = "PaperFatcher/0.1 (+https://arxiv.org)"


def download_pdf(paper: Paper, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "paper.pdf"
    logger.info("downloading PDF %s -> %s", paper.pdf_url, out)
    with requests.get(paper.pdf_url, headers={"User-Agent": _UA},
                      stream=True, timeout=120) as r:
        r.raise_for_status()
        with out.open("wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    return out


def extract_text(pdf_path: Path, *, max_chars: int = 200_000) -> str:
    """Extract readable text from a PDF, lightly cleaned."""
    doc = fitz.open(str(pdf_path))
    pages: list[str] = []
    try:
        for page in doc:
            pages.append(page.get_text("text"))
    finally:
        doc.close()
    text = "\n\n".join(pages)

    # Drop the references section onward — most papers have it and it bloats
    # the prompt without helping the dialogue.
    text = re.split(
        r"\n\s*(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n",
        text, maxsplit=1,
    )[0]

    # Collapse runs of blank lines and de-hyphenate end-of-line word breaks.
    text = re.sub(r"-\n([a-z])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Drop NULs and other C0 control chars (except \t \n \r) — pymupdf
    # occasionally emits them and subprocess argv refuses NULs outright.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.strip()

    if len(text) > max_chars:
        logger.info("paper text %d chars; truncating to %d", len(text), max_chars)
        text = text[:max_chars]
    logger.info("extracted %d chars from %s", len(text), pdf_path.name)
    return text


def write_digest(paper: Paper, paper_text: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    prompt = (
        "Summarize the arXiv paper below in ONE paragraph (4-6 sentences) "
        "for a research-savvy reader. Cover the problem, the key idea, the "
        "method at a high level, and the headline result with concrete "
        "numbers if stated. No marketing tone, no bullet lists, no hedging "
        "filler.\n\n"
        f"Title: {paper.title}\n\n"
        f"Authors: {', '.join(paper.authors[:8])}"
        f"{' et al.' if len(paper.authors) > 8 else ''}\n\n"
        f"=== Abstract ===\n{paper.abstract}\n\n"
        f"=== Paper text ===\n{paper_text}"
    )
    paragraph = claude_cli.text(prompt, label="digest", timeout=420)

    md = (
        f"# {paper.title}\n\n"
        f"**arXiv:** [{paper.id}]({paper.abs_url}) — {paper.primary_category}  \n"
        f"**Authors:** {', '.join(paper.authors)}  \n"
        f"**Published:** {paper.published:%Y-%m-%d %H:%M UTC}\n\n"
        f"## Digest\n\n{paragraph}\n\n"
        f"## Abstract\n\n{paper.abstract}\n"
    )
    out = dest_dir / "digest.md"
    out.write_text(md, encoding="utf-8")
    logger.info("wrote %s (%d chars)", out, len(md))
    return out
