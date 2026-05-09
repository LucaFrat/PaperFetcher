"""arXiv RSS fetcher: 72h window, dedup against picked.json."""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

_UA = "PaperFatcher/0.1 (+mailto:frattini77.lf@gmail.com)"
_RSS_URL = "https://export.arxiv.org/rss/{cat}"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

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


def _parse_id(guid: str, fallback_link: str) -> str:
    # guid like "oai:arXiv.org:2605.05208v1" → "2605.05208"
    m = re.search(r"arXiv\.org:([^v\s]+)", guid)
    if m:
        return m.group(1)
    m = re.search(r"abs/([^v\s]+)", fallback_link)
    return m.group(1) if m else guid


def _parse_description(desc: str) -> tuple[str, str]:
    """Return (announce_type, abstract). Description format:
       'arXiv:<id>v<n> Announce Type: <type>\nAbstract: <abstract>'
    """
    m = re.search(r"Announce Type:\s*([a-z]+)", desc, re.IGNORECASE)
    announce = (m.group(1).lower() if m else "new")
    am = re.search(r"Abstract:\s*(.+)", desc, re.DOTALL | re.IGNORECASE)
    abstract = am.group(1).strip() if am else desc.strip()
    abstract = re.sub(r"\s+", " ", abstract)
    return announce, abstract


def _parse_authors(creator: str | None) -> list[str]:
    if not creator:
        return []
    # arXiv RSS dc:creator is comma-separated names
    return [a.strip() for a in creator.split(",") if a.strip()]


def _parse_pubdate(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _fetch_category(cat: str, *, timeout: int = 30) -> list[Paper]:
    url = _RSS_URL.format(cat=cat)
    logger.info("RSS GET %s", url)
    r = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    channel = root.find("channel")
    if channel is None:
        logger.warning("no <channel> in RSS for %s", cat)
        return []

    out: list[Paper] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pubdate = _parse_pubdate(item.findtext("pubDate"))
        creator = item.findtext(f"{{{_DC_NS}}}creator")

        announce, abstract = _parse_description(desc)
        if announce != "new":
            continue  # skip "replace" and "cross" entries

        sid = _parse_id(guid, link)
        if not sid or not title or not abstract:
            continue

        out.append(
            Paper(
                id=sid,
                title=re.sub(r"\s+", " ", title).strip(),
                authors=_parse_authors(creator),
                abstract=abstract,
                pdf_url=f"https://arxiv.org/pdf/{sid}",
                abs_url=link or f"https://arxiv.org/abs/{sid}",
                published=pubdate,
                primary_category=cat,
            )
        )
    logger.info("  parsed %d new items from %s", len(out), cat)
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

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    seen: set[str] = set()
    papers: list[Paper] = []

    for i, cat in enumerate(categories):
        if i > 0:
            time.sleep(request_delay_seconds)
        try:
            entries = _fetch_category(cat)
        except requests.RequestException as e:
            logger.warning("RSS fetch for %s failed: %s", cat, e)
            continue

        for p in entries:
            if p.id in seen or p.id in exclude_ids:
                continue
            if p.published < cutoff:
                continue
            seen.add(p.id)
            papers.append(p)

    logger.info("fetched %d papers from %d categories (cutoff %s, excluded %d)",
                len(papers), len(categories), cutoff.isoformat(), len(exclude_ids))
    return papers
