"""Subprocess wrapper around `claude -p`: text + JSON-schema modes, cost logging."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class ClaudeCLIError(RuntimeError):
    pass


def _run(args: list[str], *, timeout: int) -> str:
    try:
        proc = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as e:
        raise ClaudeCLIError("claude CLI not on PATH — install + `claude login`") from e
    except subprocess.CalledProcessError as e:
        raise ClaudeCLIError(
            f"claude exited {e.returncode}: {(e.stderr or '')[:500]}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude timed out after {timeout}s") from e
    return proc.stdout


def _result_event(events: list[dict]) -> dict:
    for ev in events:
        if ev.get("type") == "result":
            return ev
    raise ClaudeCLIError("claude JSON stream had no result event")


def _invoke_json(args: list[str], *, label: str, timeout: int) -> dict:
    out = _run(args, timeout=timeout)
    try:
        events = json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(f"claude stdout was not JSON: {out[:500]}") from e
    if not isinstance(events, list):
        raise ClaudeCLIError(f"claude stdout was not a JSON array: {out[:200]}")
    result = _result_event(events)
    if result.get("is_error"):
        raise ClaudeCLIError(
            f"claude reported error: {result.get('api_error_status')} — "
            f"{result.get('result', '')[:300]}"
        )
    cost = result.get("total_cost_usd")
    dur_ms = result.get("duration_ms")
    turns = result.get("num_turns")
    logger.info("claude %s: $%.4f equiv | %dms | %d turn%s",
                label, cost or 0.0, dur_ms or 0,
                turns or 0, "" if turns == 1 else "s")
    return result


def text(prompt: str, *, label: str = "text", timeout: int = 240,
         model: str = "claude-opus-4-7[1m]", effort: str = "max") -> str:
    """Plain-text response from `claude -p`."""
    result = _invoke_json(
        ["claude", "-p", prompt, "--output-format", "json",
         "--model", model, "--effort", effort],
        label=label, timeout=timeout,
    )
    raw = result.get("result")
    if not isinstance(raw, str):
        raise ClaudeCLIError("claude result event missing .result string")
    return raw.strip()


def json_obj(prompt: str, *, schema: dict, label: str = "json",
             timeout: int = 360, model: str = "opus",
             effort: str = "medium") -> Any:
    """Schema-validated JSON response. `schema` is a real JSON Schema dict."""
    result = _invoke_json(
        [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--model", model,
            "--effort", effort,
        ],
        label=label, timeout=timeout,
    )
    if "structured_output" in result:
        return result["structured_output"]
    raw = result.get("result")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ClaudeCLIError(
                f"no structured_output and .result was not JSON: {raw[:300]}"
            ) from e
    raise ClaudeCLIError("claude result event had neither structured_output nor .result")
