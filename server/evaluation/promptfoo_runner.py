"""Real Promptfoo regression runs over the eval dataset.

Generates a Promptfoo config from the corpus eval dataset, runs the installed
``promptfoo`` CLI against the authenticated LiteLLM gateway (prompts answered by
the chat alias, ``llm-rubric`` assertions graded by the configured grader
alias), and returns the parsed results. Nothing here fabricates outcomes: if
the CLI, Node runtime, or gateway cannot execute, it raises
``PromptfooUnavailableError`` so callers fail closed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from server.chat.gateway_runtime import resolve_litellm_api_key, resolve_litellm_base_url
from server.models.tribrid_config_model import PromptfooRun, PromptfooRunResult, TriBridConfig

_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_BIN = _ROOT / "web" / "node_modules" / ".bin" / "promptfoo"


class PromptfooUnavailableError(RuntimeError):
    """Raised when a Promptfoo regression cannot execute for a real, named reason."""


@dataclass(frozen=True)
class PromptfooTest:
    entry_id: str
    question: str
    expected_answer: str


def promptfoo_binary() -> Path | None:
    if _LOCAL_BIN.exists():
        return _LOCAL_BIN
    found = shutil.which("promptfoo")
    return Path(found) if found else None


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    node_bin = str(env.get("RAGWELD_NODE_BIN") or "").strip()
    if node_bin:
        env["PATH"] = f"{Path(node_bin).parent}{os.pathsep}{env.get('PATH', '')}"
    env.setdefault("PROMPTFOO_DISABLE_TELEMETRY", "1")
    env.setdefault("PROMPTFOO_DISABLE_UPDATE", "1")
    return env


def promptfoo_version() -> str:
    """Return the CLI version by executing it; raise when it cannot run."""
    binary = promptfoo_binary()
    if binary is None:
        raise PromptfooUnavailableError("promptfoo CLI is not installed (expected web/node_modules/.bin/promptfoo)")
    try:
        completed = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            env=_subprocess_env(),
            check=False,
        )
    except Exception as exc:
        raise PromptfooUnavailableError(f"promptfoo CLI could not start: {type(exc).__name__}") from exc
    output = (completed.stdout or "").strip().splitlines()
    version = output[-1].strip() if output else ""
    if completed.returncode != 0 or not version or "requires" in (completed.stdout + completed.stderr).lower():
        raise PromptfooUnavailableError(
            "promptfoo CLI refused to run: "
            + ((completed.stderr or completed.stdout).strip()[:200] or f"exit {completed.returncode}")
            + " (set RAGWELD_NODE_BIN to a supported Node.js runtime)"
        )
    return version


def _gateway(cfg: TriBridConfig) -> tuple[str, str]:
    try:
        base_url = resolve_litellm_base_url(configured_url=str(cfg.chat.litellm.base_url or ""))
        api_key = resolve_litellm_api_key()
    except RuntimeError as exc:
        raise PromptfooUnavailableError(str(exc)) from exc
    return base_url, api_key


def _aliases(cfg: TriBridConfig) -> tuple[str, str]:
    provider = str(cfg.chat.litellm.default_model or "").strip()
    grader = str(cfg.evaluation.promptfoo_grader_model or "").strip() or provider
    if not provider:
        raise PromptfooUnavailableError("chat.litellm.default_model is empty; no gateway alias to answer prompts")
    return provider, grader


def preflight(cfg: TriBridConfig) -> str:
    """Verify CLI, runtime, and gateway; return the promptfoo version."""
    version = promptfoo_version()
    base_url, api_key = _gateway(cfg)
    provider, grader = _aliases(cfg)
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(5.0, connect=2.0),
        )
    except Exception as exc:
        raise PromptfooUnavailableError(f"LiteLLM gateway unreachable at {base_url}: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise PromptfooUnavailableError(f"LiteLLM gateway rejected the client key (HTTP {response.status_code})")
    try:
        ids = {str(item.get("id") or "") for item in (response.json().get("data") or [])}
    except Exception:
        ids = set()
    for alias in {provider, grader}:
        if alias not in ids:
            raise PromptfooUnavailableError(f"alias {alias!r} is not exposed by the LiteLLM gateway")
    return version


def _ragweld_api_base() -> str:
    """The host API that Promptfoo exercises (deployment wiring, not config)."""
    port = str(os.environ.get("BACKEND_PORT") or "58012").strip()
    return f"http://127.0.0.1:{port}/api"


def _build_config(cfg: TriBridConfig, tests: list[PromptfooTest], *, repo_id: str) -> dict[str, Any]:
    base_url, _ = _gateway(cfg)
    provider, grader = _aliases(cfg)
    # The system under test is ragweld's own grounded answer path, not a bare
    # model: each test posts the question to /api/answer for this corpus.
    provider_spec = {
        "id": "https",
        "label": f"ragweld /api/answer ({provider})",
        "config": {
            "url": f"{_ragweld_api_base()}/answer",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": {
                "query": "{{question}}",
                "repo_id": repo_id,
                "include_vector": True,
                "include_sparse": True,
                "include_graph": bool(cfg.graph_search.enabled),
                "cache_mode": "bypass",
            },
            "transformResponse": "json.answer",
        },
    }
    grader_spec = {
        "id": f"openai:chat:{grader}",
        "config": {
            "apiBaseUrl": base_url,
            "temperature": 0,
            "max_tokens": int(cfg.chat.max_tokens),
            # Graders must emit the rubric JSON, not reasoning traces.
            "passthrough": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    }
    return {
        "description": "ragweld eval dataset regression",
        "prompts": ["{{question}}"],
        "providers": [provider_spec],
        "defaultTest": {"options": {"provider": grader_spec}},
        "tests": [
            {
                "description": test.entry_id,
                "vars": {"question": test.question, "entry_id": test.entry_id, "expected_answer": test.expected_answer},
                "assert": [{"type": "llm-rubric", "value": test.expected_answer}],
            }
            for test in tests
        ],
    }


def run_regression(cfg: TriBridConfig, *, repo_id: str, tests: list[PromptfooTest], skipped_entries: int) -> PromptfooRun:
    version = preflight(cfg)
    if not tests:
        raise PromptfooUnavailableError(
            "no eval dataset entries carry an expected_answer; Promptfoo llm-rubric regression needs at least one"
        )
    base_url, api_key = _gateway(cfg)
    provider, grader = _aliases(cfg)
    started_at = datetime.now(UTC)
    binary = promptfoo_binary()
    assert binary is not None

    with tempfile.TemporaryDirectory(prefix="ragweld-promptfoo-") as tmp:
        config_path = Path(tmp) / "promptfooconfig.json"
        output_path = Path(tmp) / "results.json"
        config_path.write_text(json.dumps(_build_config(cfg, tests, repo_id=repo_id), indent=2), encoding="utf-8")
        env = _subprocess_env()
        env["OPENAI_API_KEY"] = api_key
        env["OPENAI_BASE_URL"] = base_url
        env["PROMPTFOO_CONFIG_DIR"] = str(Path(tmp) / "state")
        try:
            completed = subprocess.run(
                [
                    str(binary),
                    "eval",
                    "-c",
                    str(config_path),
                    "-o",
                    str(output_path),
                    "--no-cache",
                    "--no-progress-bar",
                    "--max-concurrency",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=float(cfg.evaluation.ragas_judge_timeout_s) * max(1, len(tests)) * 2,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PromptfooUnavailableError("promptfoo eval timed out against the gateway") from exc
        if not output_path.exists():
            raise PromptfooUnavailableError(
                "promptfoo eval produced no results: " + (completed.stderr or completed.stdout).strip()[-300:]
            )
        payload = json.loads(output_path.read_text(encoding="utf-8"))

    results_raw = (payload.get("results") or {}).get("results") or []
    parsed: list[PromptfooRunResult] = []
    for item in results_raw:
        vars_ = item.get("vars") or {}
        grade = item.get("gradingResult") or {}
        components = grade.get("componentResults") or []
        reason = str(grade.get("reason") or (components[0].get("reason") if components else "") or "")
        response = item.get("response") or {}
        parsed.append(
            PromptfooRunResult(
                entry_id=str(vars_.get("entry_id") or item.get("description") or ""),
                question=str(vars_.get("question") or ""),
                expected_answer=str(vars_.get("expected_answer") or ""),
                response=str(response.get("output") or ""),
                passed=bool(item.get("success")),
                score=max(0.0, min(1.0, float(item.get("score") or 0.0))),
                reason=reason[:500],
                latency_ms=float(item.get("latencyMs") or 0.0),
            )
        )
    completed_at = datetime.now(UTC)
    passed = sum(1 for r in parsed if r.passed)
    return PromptfooRun(
        run_id=f"{repo_id}__promptfoo__{completed_at.strftime('%Y%m%d_%H%M%S')}",
        repo_id=repo_id,
        provider_alias=provider,
        grader_alias=grader,
        promptfoo_version=version,
        total=len(parsed),
        passed=passed,
        failed=len(parsed) - passed,
        skipped_entries=int(skipped_entries),
        started_at=started_at,
        completed_at=completed_at,
        results=parsed,
    )
