"""Two-stage dialogue generator: outline (Claude text) → JSON-schema dialogue (Claude)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import claude_cli
from .fetch import Paper

logger = logging.getLogger(__name__)


def _build_outline(paper: Paper, paper_text: str) -> str:
    prompt = (
        "You are preparing two well-informed co-hosts to discuss an arXiv "
        "paper on a podcast. Read the full paper and produce a structured "
        "outline of what they should actually talk about. The dialogue itself "
        "comes later — this is the cheat sheet they will riff on.\n\n"
        "Cover, with concrete details lifted directly from the paper:\n"
        "  1. The problem and why it matters now\n"
        "  2. What prior work tried, and the specific gap or failure mode "
        "(name baselines if mentioned)\n"
        "  3. The key insight or core idea — the one-sentence \"why this "
        "works\"\n"
        "  4. Method specifics: architecture, training procedure, datasets, "
        "key hyperparameters or design choices stated in the paper\n"
        "  5. Headline experimental result with specific numbers (datasets, "
        "baselines, metric values, gains)\n"
        "  6. The most interesting ablation or analysis result\n"
        "  7. Limitations the authors acknowledge, plus any honest open "
        "questions\n"
        "  8. Why this matters for the broader field — what does it unlock\n\n"
        "Be specific. Use exact numbers and names from the paper. Avoid "
        "generalities like \"better performance\" — say \"+15.3% on RoboCasa-"
        "GR1\" or whatever the paper actually reports. If the paper does not "
        "support a claim, omit it.\n\n"
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors)}\n"
        f"arXiv: {paper.id}\n\n"
        f"=== Abstract ===\n{paper.abstract}\n\n"
        f"=== Full paper text ===\n{paper_text}"
    )
    return claude_cli.text(prompt, label="outline", timeout=900)


def _build_dialogue(paper: Paper, paper_text: str, outline: str,
                    *, target_minutes: int) -> dict:
    words_lo = round(target_minutes * 140)
    words_hi = round(target_minutes * 170)
    lines_lo = max(20, round(target_minutes * 3.5))
    lines_hi = max(28, round(target_minutes * 4.5))
    prompt = (
        "Write a podcast-style dialogue between two co-hosts (A and B) "
        f"discussing the arXiv paper below. Target ~{target_minutes} minutes "
        f"of audio — roughly {words_lo}-{words_hi} words total across both "
        f"speakers, about {lines_lo}-{lines_hi} lines that vary in length "
        "(one sentence to a short paragraph). "
        "A is the curious one driving the conversation; B is the expert "
        "who has read the paper deeply. Use natural speech: contractions, "
        "occasional asides, light humor. Don't pad — every exchange should "
        "advance understanding.\n\n"
        "Quality bar: a researcher in this subfield should listen and feel "
        "they learned something specific they could not have gotten from the "
        "abstract alone. Hit real numbers, real method choices, real "
        "comparisons. Avoid 'the authors propose a novel approach' filler. "
        "Don't invent facts not in the outline or paper text.\n\n"
        "AUDIO-ONLY COMPREHENSIBILITY — strict rules. The listener has only "
        "their ears, no PDF in front of them:\n"
        "  • NEVER reference a figure, table, equation, section, or appendix "
        "by number ('Figure 1', 'Equation 12', 'Table 3', 'Section 4.2', "
        "'the appendix'). If a figure is conceptually important, describe "
        "the picture in words ('picture a robot arm reaching for a cube...').\n"
        "  • DO NOT explain the math. No formulas, no Greek letters, no "
        "discount-factor-to-the-k-th-power, no 'gamma times something'. "
        "Talk about WHAT the math achieves, not how it computes. "
        "Bad: 'they normalize Q by gamma to the k.' "
        "Good: 'they correct for the fact that shorter action chunks look "
        "artificially better, then they pick the chunk length that wins on "
        "that corrected score.' If a step in the method is fundamentally "
        "mathematical, describe its purpose in one sentence and move on.\n"
        "  • Numbers from tables: state them in conversation ('they hit "
        "78.2% on the benchmark, versus 65% for the previous best').\n"
        "  • Acronyms: expand on first use, then you can shorten. 'RL' should "
        "be 'reinforcement learning' the first time it comes up.\n"
        "  • If the paper uses a notation you'd want a listener to remember, "
        "give it a verbal name ('what they call the advantage score').\n"
        "Failure to follow these rules = the dialogue is broken.\n\n"
        "Open by naming the paper and authors. Then move through the "
        "discussion outline below in roughly its order, but treat it as a "
        "conversation, not a checklist. End on the discussion itself — no "
        "filler intros ('welcome back to'), no sponsor reads, no sign-off "
        "that mentions subscribing.\n\n"
        f"=== Discussion outline (your cheat sheet) ===\n{outline}\n\n"
        f"=== Title ===\n{paper.title}\n\n"
        f"=== Authors ===\n{', '.join(paper.authors)}\n\n"
        f"=== Full paper text (ground truth — quote when useful) ===\n"
        f"{paper_text}"
    )
    schema = {
        "type": "object",
        "properties": {
            "dialogue": {
                "type": "array",
                "minItems": max(20, round(target_minutes * 2.4)),
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string", "enum": ["A", "B"]},
                        "text": {"type": "string"},
                    },
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["dialogue"],
        "additionalProperties": False,
    }
    return claude_cli.json_obj(prompt, schema=schema, label="script",
                               timeout=900)


def generate(paper: Paper, paper_text: str, dest_dir: Path,
             *, target_minutes: int = 10) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    outline = _build_outline(paper, paper_text)
    (dest_dir / "outline.md").write_text(outline, encoding="utf-8")
    logger.info("wrote outline.md (%d chars)", len(outline))

    obj = _build_dialogue(paper, paper_text, outline, target_minutes=target_minutes)

    if not isinstance(obj, dict) or "dialogue" not in obj:
        raise ValueError(f"script JSON missing .dialogue: {str(obj)[:300]}")
    lines = obj["dialogue"]
    if not isinstance(lines, list) or not lines:
        raise ValueError("script .dialogue is empty or not a list")

    cleaned: list[dict] = []
    for i, ln in enumerate(lines):
        spk = str(ln.get("speaker", "")).strip().upper()
        txt = str(ln.get("text", "")).strip()
        if spk not in ("A", "B"):
            raise ValueError(f"line {i} has bad speaker {spk!r}")
        if not txt:
            continue
        cleaned.append({"speaker": spk, "text": txt})
    if not cleaned:
        raise ValueError("script has no non-empty lines after cleanup")

    out = dest_dir / "script.json"
    out.write_text(json.dumps({"dialogue": cleaned}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    total_chars = sum(len(l["text"]) for l in cleaned)
    logger.info("wrote %s (%d lines, ~%d chars)", out, len(cleaned), total_chars)
    return out
