#!/usr/bin/env python3
"""Generate full-fidelity glossary.json from legacy tooltip HTML.

Goal:
- Preserve the hard-won tooltip content from the legacy tooltip map
- Move it into `data/glossary.json` (tracked) and `web/public/glossary.json` (served by Vite)
- Keep only *external* links (http/https); strip internal doc links per project direction

This script is deterministic and safe to run repeatedly.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GlossaryLink:
    text: str
    href: str


@dataclass(frozen=True)
class GlossaryBadge:
    text: str
    class_name: str


@dataclass(frozen=True)
class ParsedTooltip:
    term: str
    definition_html: str
    links: list[GlossaryLink]
    badges: list[GlossaryBadge]


_TITLE_RE = re.compile(r'<span\s+class="tt-title">(?P<title>.*?)</span>', re.DOTALL)
_BADGES_BLOCK_RE = re.compile(r'<div\s+class="tt-badges">(?P<body>.*?)</div>', re.DOTALL)
_BADGE_RE = re.compile(r'<span\s+class="tt-badge\s*(?P<class>[^"]*)">(?P<text>.*?)</span>', re.DOTALL)
_LINKS_BLOCK_RE = re.compile(r'<div\s+class="tt-links">(?P<body>.*?)</div>', re.DOTALL)
_LINK_RE = re.compile(r'<a\s+href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>', re.DOTALL)
_BODY_DIV_RE = re.compile(r'^\s*<div>(?P<body>.*)</div>\s*$', re.DOTALL)


def _strip_tags(text: str) -> str:
    # Tooltip titles are expected to be plain, but be defensive.
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\\s+", " ", text).strip()


def _escape_placeholder_tags(html: str) -> str:
    # Legacy tooltips contain placeholder tags like <SCHEME> which TooltipIcon will drop.
    # Escape them so they render as literal text.
    for token in ("SCHEME", "HOST", "PORT", "NEW_PORT"):
        html = html.replace(f"<{token}>", f"&lt;{token}&gt;")
        html = html.replace(f"</{token}>", f"&lt;/{token}&gt;")
    return html


def _is_external_href(href: str) -> bool:
    href = (href or "").strip()
    return href.startswith("http://") or href.startswith("https://")


def _parse_tooltip_html(key: str, html: str) -> ParsedTooltip:
    html = html or ""

    m_title = _TITLE_RE.search(html)
    title_raw = m_title.group("title") if m_title else key
    term = _strip_tags(title_raw) or key

    badges: list[GlossaryBadge] = []
    m_badges = _BADGES_BLOCK_RE.search(html)
    if m_badges:
        for bm in _BADGE_RE.finditer(m_badges.group("body")):
            text = _strip_tags(bm.group("text"))
            cls = (bm.group("class") or "").strip()
            badges.append(GlossaryBadge(text=text, class_name=cls))

    links: list[GlossaryLink] = []
    m_links = _LINKS_BLOCK_RE.search(html)
    if m_links:
        for lm in _LINK_RE.finditer(m_links.group("body")):
            href = (lm.group("href") or "").strip()
            if not _is_external_href(href):
                continue
            text = _strip_tags(lm.group("text"))
            if not text:
                continue
            links.append(GlossaryLink(text=text, href=href))

    # Remove title/badges/links blocks, leaving the main <div>...</div> body wrapper.
    body_html = _TITLE_RE.sub("", html, count=1)
    body_html = _BADGES_BLOCK_RE.sub("", body_html, count=1)
    body_html = _LINKS_BLOCK_RE.sub("", body_html, count=1)
    body_html = body_html.strip()
    m_body = _BODY_DIV_RE.match(body_html)
    definition_html = (m_body.group("body") if m_body else body_html).strip()
    definition_html = _escape_placeholder_tags(definition_html)

    return ParsedTooltip(term=term, definition_html=definition_html, links=links, badges=badges)


def _load_existing_glossary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": "1.0.0", "generated_from": None, "terms": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_legacy_tooltip_map() -> dict[str, str]:
    # Use Node to import the legacy tooltip map deterministically (no parsing JS in Python).
    #
    # NOTE: Some forks removed the legacy tooltip module entirely. In that case, callers should
    # skip this and treat `data/glossary.json` as the source of truth.
    cmd = [
        "node",
        "--input-type=module",
        "-e",
        (
            "import { tooltipMap } from './web/src/modules/_archived/tooltips.js';"
            "process.stdout.write(JSON.stringify(tooltipMap));"
        ),
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    try:
        data = json.loads(res.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to parse tooltipMap JSON from node: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("tooltipMap from legacy module is not a dict")
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _find_tooltipicon_literal_keys(web_src: Path) -> set[str]:
    # Only capture literal TooltipIcon names; dynamic ones (name={...}) are handled elsewhere.
    pattern = re.compile(r'<TooltipIcon\s+[^>]*name="([^"]+)"')
    keys: set[str] = set()
    for tsx in web_src.rglob("*.tsx"):
        text = tsx.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            keys.add(m.group(1))
    return keys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    data_path = repo_root / "data" / "glossary.json"
    public_path = repo_root / "web" / "public" / "glossary.json"
    web_src = repo_root / "web" / "src"
    legacy_module = repo_root / "web" / "src" / "modules" / "_archived" / "tooltips.js"

    existing = _load_existing_glossary(data_path)
    existing_terms = existing.get("terms") if isinstance(existing, dict) else None
    if not isinstance(existing_terms, list):
        existing_terms = []

    existing_by_key: dict[str, dict[str, Any]] = {}
    for t in existing_terms:
        if isinstance(t, dict) and isinstance(t.get("key"), str):
            existing_by_key[t["key"]] = t

    legacy_map: dict[str, str] = {}
    if legacy_module.exists():
        legacy_map = _load_legacy_tooltip_map()
    ui_keys = _find_tooltipicon_literal_keys(web_src)

    merged: dict[str, dict[str, Any]] = {}

    if legacy_map:
        # 1) Legacy tooltip map is authoritative for tooltip content.
        for key in sorted(legacy_map.keys()):
            parsed = _parse_tooltip_html(key, legacy_map[key])
            prior = existing_by_key.get(key, {})
            category = prior.get("category") if isinstance(prior.get("category"), str) else "general"
            related = prior.get("related") if isinstance(prior.get("related"), list) else []

            merged[key] = {
                "term": parsed.term,
                "key": key,
                "definition": parsed.definition_html,
                "category": category,
                "related": related,
                "links": [{"text": l.text, "href": l.href} for l in parsed.links],
                "badges": [{"text": b.text, "class": b.class_name} for b in parsed.badges],
            }

        # 2) Keep existing glossary-only entries.
        for key, prior in existing_by_key.items():
            if key in merged:
                continue
            merged[key] = {
                "term": prior.get("term") if isinstance(prior.get("term"), str) else key,
                "key": key,
                "definition": prior.get("definition") if isinstance(prior.get("definition"), str) else "",
                "category": prior.get("category") if isinstance(prior.get("category"), str) else "general",
                "related": prior.get("related") if isinstance(prior.get("related"), list) else [],
                "links": prior.get("links") if isinstance(prior.get("links"), list) else [],
                "badges": prior.get("badges") if isinstance(prior.get("badges"), list) else [],
            }
    else:
        # Legacy module missing: treat data/glossary.json as authoritative.
        for key, prior in existing_by_key.items():
            merged[key] = {
                "term": prior.get("term") if isinstance(prior.get("term"), str) else key,
                "key": key,
                "definition": prior.get("definition") if isinstance(prior.get("definition"), str) else "",
                "category": prior.get("category") if isinstance(prior.get("category"), str) else "general",
                "related": prior.get("related") if isinstance(prior.get("related"), list) else [],
                "links": prior.get("links") if isinstance(prior.get("links"), list) else [],
                "badges": prior.get("badges") if isinstance(prior.get("badges"), list) else [],
            }

    # 3) Ensure all TooltipIcon literal keys exist.
    for key in sorted(ui_keys):
        if key in merged:
            continue
        merged[key] = {
            "term": key,
            "key": key,
            "definition": "No detailed tooltip available yet.",
            "category": "general",
            "related": [],
            "links": [],
            "badges": [],
        }

    # Stable ordering by key.
    terms_out = [merged[k] for k in sorted(merged.keys())]
    out = {
        "version": "1.1.0",
        "generated_from": "web/src/modules/_archived/tooltips.js" if legacy_map else "data/glossary.json",
        "terms": terms_out,
    }

    _dump_json(data_path, out)
    _dump_json(public_path, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
