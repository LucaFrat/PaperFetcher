"""arXiv API fetcher: queries by submittedDate range, dedup against picked.json."""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

_UA = "PaperFatcher/0.1 (+mailto:frattini77.lf@gmail.com)"
_API_URL = "http://export.arxiv.org/api/query"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_OS_NS = "http://a9.com/-/spec/opensearch/1.1/"

# Per-query cap. cs.LG can exceed 200/day so 500 comfortably covers a 72h
# window; if we ever hit it we'd need pagination via the `start` parameter.
_MAX_RESULTS_PER_CATEGORY = 500

# arXiv categories the pipeline pulls from. PaperFetcher targets the AI /
# robotics community, so this set is hardcoded — the per-user filtering
# happens later (embedding ranker + Claude) using config/interests.md prose.
DEFAULT_CATEGORIES: list[str] = [
    "cs.AI",   # Artificial Intelligence
    "cs.LG",   # Machine Learning
    "cs.RO",   # Robotics
    "cs.CV",   # Computer Vision
    "cs.CL",   # Computation and Language (NLP / LLMs)
]


@dataclass(frozen=True)
class Paper:
    id: str            # short id, e.g. "2605.05208"
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str
    abs_url: str
    published: datetime
    primary_category: str


def _parse_id(entry_id: str) -> str:
    # entry_id like "http://arxiv.org/abs/2605.05208v1" → "2605.05208"
    m = re.search(r"/abs/([^v\s/]+)", entry_id)
    return m.group(1) if m else entry_id


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        # arXiv emits '2026-05-14T12:34:56Z'
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _api_get(params: dict, *, timeout: int) -> requests.Response:
    """GET against the arXiv API with backoff on transient errors.

    arXiv applies per-IP rate limits and frequently returns 429 or slow
    responses under load. Retrying with backoff is the documented advice;
    without it a single hot IP (e.g. a shared university NAT) can starve
    the daily run.
    """
    backoffs = (10, 30)  # two retries, then give up
    last_exc: Exception | None = None
    for attempt in range(len(backoffs) + 1):
        try:
            r = requests.get(_API_URL, params=params,
                             headers={"User-Agent": _UA}, timeout=timeout)
            # 429 = rate-limited, 5xx = arxiv being slow/sick. Both are transient.
            if (r.status_code == 429 or r.status_code >= 500) \
                    and attempt < len(backoffs):
                wait = backoffs[attempt]
                logger.warning("  HTTP %d; sleeping %ds then retrying",
                               r.status_code, wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < len(backoffs):
                wait = backoffs[attempt]
                logger.warning("  transient error (%s); sleeping %ds then retrying",
                               type(e).__name__, wait)
                time.sleep(wait)
                continue
            raise
    # Unreachable: loop either returns or raises.
    raise last_exc if last_exc else RuntimeError("unreachable")


def _fetch_category(
    cat: str,
    *,
    since: datetime,
    until: datetime,
    timeout: int = 60,
) -> list[Paper]:
    params = {
        "search_query": (
            f"cat:{cat} AND submittedDate:["
            f"{since.strftime('%Y%m%d%H%M')} TO {until.strftime('%Y%m%d%H%M')}]"
        ),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(_MAX_RESULTS_PER_CATEGORY),
    }
    logger.info("API GET %s [%s]", _API_URL, cat)
    r = _api_get(params, timeout=timeout)
    root = ET.fromstring(r.content)

    # Surface pagination risk: if totalResults > our cap we silently miss
    # the oldest entries (sort is desc, so we keep the newest).
    total_txt = root.findtext(f"{{{_OS_NS}}}totalResults")
    try:
        total = int(total_txt) if total_txt else 0
    except ValueError:
        total = 0
    if total > _MAX_RESULTS_PER_CATEGORY:
        logger.warning("  %s: %d results > cap %d (dropped %d oldest)",
                       cat, total, _MAX_RESULTS_PER_CATEGORY,
                       total - _MAX_RESULTS_PER_CATEGORY)

    out: list[Paper] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        entry_id = (entry.findtext(f"{{{_ATOM_NS}}}id") or "").strip()
        title = re.sub(r"\s+", " ",
                       entry.findtext(f"{{{_ATOM_NS}}}title") or "").strip()
        abstract = re.sub(r"\s+", " ",
                          entry.findtext(f"{{{_ATOM_NS}}}summary") or "").strip()
        published = _parse_iso(entry.findtext(f"{{{_ATOM_NS}}}published"))
        authors = [
            (a.findtext(f"{{{_ATOM_NS}}}name") or "").strip()
            for a in entry.findall(f"{{{_ATOM_NS}}}author")
        ]
        authors = [a for a in authors if a]

        sid = _parse_id(entry_id)
        if not sid or not title or not abstract:
            continue

        pdf_url = f"https://arxiv.org/pdf/{sid}"
        abs_url = f"https://arxiv.org/abs/{sid}"
        for link in entry.findall(f"{{{_ATOM_NS}}}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href") or pdf_url
            elif link.get("rel") == "alternate":
                abs_url = link.get("href") or abs_url

        primary = cat
        pc = entry.find(f"{{{_ARXIV_NS}}}primary_category")
        if pc is not None and pc.get("term"):
            primary = pc.get("term")

        out.append(
            Paper(
                id=sid,
                title=title,
                authors=authors,
                abstract=abstract,
                pdf_url=pdf_url,
                abs_url=abs_url,
                published=published,
                primary_category=primary,
            )
        )
    logger.info("  parsed %d entries from %s", len(out), cat)
    return out


def fetch_recent(
    *,
    categories: list[str],
    window_hours: int,
    request_delay_seconds: float,
    exclude_ids: set[str],
) -> list[Paper]:
    if not categories:
        raise ValueError("no categories configured")

    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=window_hours)
    seen: set[str] = set()
    papers: list[Paper] = []

    for i, cat in enumerate(categories):
        if i > 0:
            time.sleep(request_delay_seconds)
        try:
            entries = _fetch_category(cat, since=since, until=until)
        except requests.RequestException as e:
            logger.warning("API fetch for %s failed: %s", cat, e)
            continue

        for p in entries:
            if p.id in seen or p.id in exclude_ids:
                continue
            seen.add(p.id)
            papers.append(p)

    logger.info("fetched %d papers from %d categories "
                "(window %s → %s, excluded %d)",
                len(papers), len(categories),
                since.isoformat(), until.isoformat(), len(exclude_ids))
    return papers
