#!/usr/bin/env python3
"""
UserPromptSubmit router (deterministic).

Reads Claude/Cursor hook JSON on stdin and returns additional context that:
- routes the request toward the appropriate repo-local skills under .codex/skills/
- restates mandatory verification requirements (Stop hook will enforce)

This script must be quiet: stdout must be *only* JSON when emitting output.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    references: tuple[str, ...]
    required_checks: tuple[str, ...]


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    h = haystack
    return any(n in h for n in needles)


def route_prompt(prompt: str) -> Route:
    p = (prompt or "").lower()

    is_docs = _contains_any(
        p,
        (
            "docs",
            "documentation",
            "mkdocs",
            "docs-autopilot",
            "docs autopilot",
            "autodoc",
        ),
    )
    is_gui = _contains_any(
        p,
        (
            "ui",
            "gui",
            "frontend",
            "react",
            "tsx",
            "vite",
            "css",
            "component",
            "playwright",
        ),
    )
    is_backend = _contains_any(
        p,
        (
            "backend",
            "fastapi",
            "server/",
            "server ",
            "api",
            "endpoint",
            "postgres",
            "neo4j",
            "retrieval",
            "indexing",
            "pydantic",
        ),
    )
    is_guardrails = _contains_any(
        p,
        (
            "hook",
            "hooks",
            "stop hook",
            "verify-tribrid",
            "guardrail",
            "skills",
        ),
    )

    references: list[str] = [
        "/Users/davidmontgomery/ragweld/AGENTS.md",
        "/Users/davidmontgomery/ragweld/docs/index.md",
    ]
    required: list[str] = []

    if is_docs:
        references.extend(
            [
                "/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md",
                "/Users/davidmontgomery/ragweld/docs/references/index.md",
            ]
        )
        required.extend(
            [
                "Docs prompts must treat mkdocs/** and mkdocs.yml as docs-autopilot output, not hand-edited source files.",
                "When docs behavior changes, update AGENTS/docs KB/scripts/docs_ai inputs instead of published MkDocs pages.",
            ]
        )

    if is_gui:
        required.extend(
            [
                "GUI changes require real Playwright E2E (no request interception).",
                "Start stack: ./start.sh --with-observability",
                "Run: uv run python scripts/check_docs_ownership.py",
                "Run: npm --prefix web run lint && npm --prefix web run build",
                "Run: npm --prefix web exec playwright test --config ../playwright.config.ts --project web",
            ]
        )

    if is_backend or is_guardrails:
        required.extend(
            [
                "Backend/API/retrieval changes require real pytest (no mocked green).",
                "Run: uv run python scripts/check_docs_ownership.py",
                "Run: uv run scripts/check_banned.py",
                "Run: uv run scripts/validate_types.py",
                "Run: uv run pytest -q",
            ]
        )

    if not required:
        required = [
            "Follow the verification loop for this change type (Stop hook will enforce).",
            "Prefer Pydantic-first shapes; keep single sources of truth.",
        ]

    # De-dupe while preserving order
    seen: set[str] = set()
    required_deduped: list[str] = []
    for item in required:
        if item in seen:
            continue
        seen.add(item)
        required_deduped.append(item)

    return Route(references=tuple(dict.fromkeys(references)), required_checks=tuple(required_deduped))


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0

    try:
        payload = json.loads(raw)
    except Exception:
        # If input isn't valid JSON, do nothing (fail open).
        return 0

    prompt = str(payload.get("prompt") or "")
    r = route_prompt(prompt)

    lines: list[str] = []
    lines.append("TriBridRAG prompt router (deterministic guardrails):")
    lines.append("")
    lines.append("Naming note:")
    lines.append("- Repo is named `ragweld`; internal identifiers still use `tribrid` in many places. This is expected.")
    lines.append("")
    lines.append("Relevant references:")
    for ref in r.references:
        lines.append(f"- `{ref}`")
    lines.append("")
    lines.append("Mandatory constraints:")
    lines.append("- Pydantic is the law (define shapes in Pydantic first; TS types from generated.ts).")
    lines.append("- No fake-green tests: no Playwright request interception; no Python mocking in new/edited tests.")
    lines.append("- `mkdocs/**` and `mkdocs.yml` are docs-autopilot output; do not hand-edit them during feature work.")
    lines.append("")
    lines.append("Required verification before completion (Stop hook will block until green):")
    for item in r.required_checks:
        lines.append(f"- {item}")

    additional = "\n".join(lines).strip() + "\n"

    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional,
        }
    }
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
