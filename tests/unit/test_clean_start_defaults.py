from __future__ import annotations

import json
import re
from pathlib import Path

from server.models.tribrid_config_model import (
    ChatConfig,
    SystemPromptsConfig,
    TrainingConfig,
    TriBridConfig,
)

ROOT = Path(__file__).resolve().parents[2]


def test_clean_start_uses_generic_model_data_and_chat_defaults() -> None:
    training = TrainingConfig()

    assert training.tribrid_reranker_model_path == "models/learning-reranker-active"
    assert training.tribrid_triplets_path == "data/training/triplets.jsonl"
    assert training.ragweld_agent_model_path == "models/learning-agent-active"
    assert ChatConfig().default_corpus_ids == ["recall_default"]


def test_clean_start_embedding_does_not_select_in_process_mlx() -> None:
    runtime_config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))

    assert runtime_config["embedding"]["embedding_backend"] == "provider"
    assert runtime_config["embedding"]["embedding_type"] == "huggingface"
    assert runtime_config["embedding"]["embedding_model_local"] == "BAAI/bge-small-en-v1.5"
    assert runtime_config["embedding"]["embedding_dim"] == 384


def test_clean_start_keeps_local_public_observability_links_for_operator_surfaces() -> None:
    defaults = TriBridConfig()
    runtime_config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))

    assert defaults.tracing.langfuse_public_base_url == "http://127.0.0.1:53000"
    assert defaults.training.ragweld_agent_mlflow_console_base_url == "http://127.0.0.1:55500"
    assert runtime_config["tracing"]["langfuse_public_base_url"] == "http://127.0.0.1:53000"
    assert runtime_config["training"]["ragweld_agent_mlflow_console_base_url"] == "http://127.0.0.1:55500"


def test_generic_runtime_surfaces_do_not_embed_optional_epstein_lane_defaults() -> None:
    generic_paths = [
        "server/models/tribrid_config_model.py",
        "tribrid_config.json",
        "data/models.json",
        "web/public/models.json",
        "web/src/types/generated.ts",
        "web/src/components/AgentTraining/TrainingStudio.tsx",
        "web/src/components/RerankerTraining/TrainingStudio.tsx",
        "web/src/components/RAG/RerankerConfigSubtab.tsx",
        "scripts/automation_bootstrap.sh",
        "web/tests/e2e/exhaustive/chat_reliability.spec.ts",
        "README.md",
        "tests/unit/test_synthetic_storage_compat.py",
    ]

    for relative_path in generic_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "epstein" not in source, relative_path


def test_catalog_has_no_corpus_specific_promoted_artifact_claim() -> None:
    source = json.loads((ROOT / "data/models.json").read_text(encoding="utf-8"))
    public = json.loads((ROOT / "web/public/models.json").read_text(encoding="utf-8"))

    assert source == public
    catalog_rows = source["models"] if isinstance(source, dict) else source
    identities = {
        (str(row.get("provider", "")), str(row.get("model", "")))
        for row in catalog_rows
        if isinstance(row, dict)
    }
    assert ("local", "learning-reranker-epstein-files-1") not in identities


def test_semantic_kg_example_is_neutral_and_optional_lane_remains_explicit() -> None:
    prompt = SystemPromptsConfig().semantic_kg_extraction

    assert "Alex Rivera" in prompt
    assert "Northwind Labs" in prompt
    assert "Denver" in prompt
    assert "Jeffrey Epstein" not in prompt

    explicit_lane_paths = [
        "server/synthetic/hf_epstein_emails.py",
        "scripts/materialize_hf_epstein_emails.py",
        "scripts/acceptance_epstein.sh",
        "scripts/automation_stop_gate.py",
        "web/tmp_synthetic_acceptance.mjs",
        "tests/unit/test_hf_epstein_emails.py",
    ]
    for relative_path in explicit_lane_paths:
        assert "epstein" in (ROOT / relative_path).read_text(encoding="utf-8").lower()

    assert not (ROOT / "models/learning-reranker-tribrid").exists()
    assert not (ROOT / "scripts/split_epstein_csv.py").exists()


def test_epstein_source_code_is_confined_to_the_explicit_domain_allowlist() -> None:
    allowlist = {
        "server/synthetic/hf_epstein_emails.py",
        "scripts/materialize_hf_epstein_emails.py",
        "scripts/acceptance_epstein.sh",
        "scripts/automation_stop_gate.py",
        # Pins the corpus that owns the completed reranker run its assertions
        # need (the Neural Visualizer regression spec).
        "web/tests/e2e/exhaustive/learning_reranker_visualizer.spec.ts",
    }
    roots = [ROOT / "server", ROOT / "web/src", ROOT / "web/tests/e2e/exhaustive", ROOT / "scripts"]
    code_suffixes = {".py", ".sh", ".js", ".mjs", ".ts", ".tsx"}

    unexpected: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in code_suffixes:
                continue
            relative_path = str(path.relative_to(ROOT))
            if relative_path in allowlist:
                continue
            if "epstein" in path.read_text(encoding="utf-8").lower():
                unexpected.append(relative_path)

    assert unexpected == []


def test_generic_automation_uses_a_stable_generated_fixture_and_explicit_lane_is_scoped() -> None:
    bootstrap = (ROOT / "scripts/automation_bootstrap.sh").read_text(encoding="utf-8")
    explicit_acceptance = (ROOT / "scripts/acceptance_epstein.sh").read_text(encoding="utf-8")

    assert 'CORPUS_ID="${CORPUS_ID:-ragweld-acceptance}"' in bootstrap
    assert 'output/automation/fixtures/$CORPUS_ID' in bootstrap
    assert "$HOME/epstein" not in bootstrap
    assert "bootstrap_corpus_mismatch" in explicit_acceptance
    assert "CORPUS_PATH=/path/to/epstein-corpus" in explicit_acceptance


def test_local_generation_models_are_current_everywhere() -> None:
    """The retired local generation models must not survive anywhere the runtime reads.

    The host vllm-metal local-model server serves mlx-community/Qwen3.8-27B-4bit; the
    Learning Agent still trains on the Qwen3-4B MLX build (training-only artifact, base
    decision tracked separately). The 0.6B/1.7B predecessors and the in-VM bf16 4B
    serving path were replaced, not kept as fallbacks. Every tracked
    code/config/UI/script/test file is scanned; only historical records (lineage,
    run artifacts, exec-plan history, docs that describe the retirement) are excluded.
    """
    import subprocess

    from server.models.runtime_gateway import GenerationConfig
    from server.models.tribrid_config_model import UIConfig, VLLMConfig

    assert VLLMConfig().default_model == "mlx-community/Qwen3.8-27B-4bit"
    assert TrainingConfig().ragweld_agent_base_model == "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    # The in-process MLX chat path is gone; its idle-unload/reload tunables went with it.
    assert "ragweld_agent_unload_after_sec" not in TrainingConfig.model_fields
    assert "ragweld_agent_reload_period_sec" not in TrainingConfig.model_fields
    # Clean-start and `/api/config/reset` must keep timeouts sized for CPU serving of the 4B model.
    assert UIConfig().chat_stream_timeout == 600
    assert GenerationConfig().gen_timeout == 600

    runtime_config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    assert runtime_config["chat"]["vllm"]["default_model"] == "mlx-community/Qwen3.8-27B-4bit"
    assert runtime_config["training"]["ragweld_agent_base_model"] == "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    assert runtime_config["ui"]["chat_stream_timeout"] == 600
    assert runtime_config["generation"]["gen_timeout"] == 600
    assert "ragweld_agent_unload_after_sec" not in runtime_config["training"]

    # "Qwen/Qwen3-4B-Instruct-2507" (with the Qwen/ prefix) is the retired bf16
    # SERVING id; the mlx-community 4-bit build of the same family remains the
    # Learning Agent training base and does not match this needle.
    retired = ("Qwen/Qwen3-0.6B", "Qwen3-1.7B-4bit", "Qwen/Qwen3-4B-Instruct-2507")
    live_prefixes = ("server/", "web/src/", "web/public/", "web/tests/", "scripts/", "infra/", "tests/", "spec/")
    live_files = {"docker-compose.yml", "start.sh", "tribrid_config.json", "data/models.json", "data/glossary.json", "README.md"}
    historical_exclusions = {
        Path(__file__).resolve().relative_to(ROOT).as_posix(),
        # Negative fixtures: these tests prove the retired base is REJECTED, so they name it.
        "tests/api/test_promotion_lineage.py",
        "tests/unit/test_agent_artifact.py",
    }
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    scanned = 0
    for relative_path in tracked:
        if not relative_path or relative_path in historical_exclusions:
            continue
        if not (relative_path.startswith(live_prefixes) or relative_path in live_files):
            continue
        target = ROOT / relative_path
        if not target.is_file():
            continue
        try:
            source = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for needle in retired:
            assert needle not in source, f"{relative_path} still references retired model {needle}"
    assert scanned > 500, f"expected to scan the live tree, scanned {scanned} files"


def test_frontend_timeout_controls_follow_the_pydantic_contract() -> None:
    """The UI may not advertise a narrower or different range than the boundary model."""
    from server.models.runtime_gateway import GenerationConfig
    from server.models.tribrid_config_model import UIConfig

    gen_field = GenerationConfig.model_fields["gen_timeout"]
    gen_le = next(m.le for m in gen_field.metadata if hasattr(m, "le"))
    gen_ge = next(m.ge for m in gen_field.metadata if hasattr(m, "ge"))
    retrieval = (ROOT / "web/src/components/RAG/RetrievalSubtab.tsx").read_text(encoding="utf-8")
    assert f"useConfigField<number>('generation.gen_timeout', {gen_field.default})" in retrieval
    assert f"min={{{gen_ge}}}\n                    max={{{gen_le}}}" in retrieval
    # The control commits through the shared NumberField (clamp on blur/Enter), not through a
    # per-keystroke snap: a lower-bounded field is impossible to type into when every keystroke
    # is clamped. The bounds themselves are enforced for every such field by
    # `test_every_number_field_advertises_its_pydantic_bounds` below.
    assert "onCommit={setGenTimeout}" in retrieval
    assert "max={300}" not in retrieval

    ui_field = UIConfig.model_fields["chat_stream_timeout"]
    ui_le = next(m.le for m in ui_field.metadata if hasattr(m, "le"))
    chat = (ROOT / "web/src/components/Chat/ChatInterface.tsx").read_text(encoding="utf-8")
    assert f"const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = {ui_field.default}_000;" in chat
    assert f"config?.ui?.chat_stream_timeout ?? {ui_field.default}" in chat
    assert f"Math.min({ui_le}, configuredChatTimeoutSeconds)" in chat


def _config_field_bounds(path: str) -> tuple[float | None, float | None]:
    """The ge/le of one dotted TriBridConfig path, e.g. ``chunking.target_tokens``."""
    from pydantic import BaseModel

    from server.models.tribrid_config_model import TriBridConfig

    parts = path.split(".")
    model: type[BaseModel] = TriBridConfig
    for part in parts[:-1]:
        model = model.model_fields[part].annotation  # type: ignore[assignment]
    info = model.model_fields[parts[-1]]
    low = high = None
    for meta in info.metadata:
        if getattr(meta, "ge", None) is not None:
            low = meta.ge
        if getattr(meta, "le", None) is not None:
            high = meta.le
    return low, high


def _jsx_elements(source: str, tag: str) -> list[str]:
    """Every ``<tag ... />`` element in a TSX source, brace-balanced so style props survive."""
    lines = source.split("\n")
    found: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(rf"^\s*<{tag}\b", lines[i]):
            depth, j, block = 0, i, []
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                block.append(lines[j])
                if depth == 0 and lines[j].rstrip().endswith("/>"):
                    break
                j += 1
            found.append("\n".join(block))
            i = j + 1
        else:
            i += 1
    return found


# Config paths whose numeric control already advertises bounds its model does not have. Every
# one is in RetrievalSubtab.tsx and predates this test: they came in with the first NumberField
# conversion, which carried the old raw inputs' hand-written min/max across unchanged. They are
# real defects -- a UI bound narrower than the model refuses a legal value, a wider one sends a
# value the PATCH rejects as an unattributed 422 -- but fixing each needs a decision about which
# side is right, so they are recorded rather than silently skipped.
#
# This list is a ratchet: the test fails if a new path joins it AND if a listed path is fixed
# without being removed. Shrink it; never grow it.
KNOWN_NUMBER_FIELD_BOUND_GAPS = frozenset(
    {
        "generation.gen_max_tokens",
        "graph_search.top_k",
        "hydration.hydration_max_chars",
        "retrieval.eval_final_k",
        "retrieval.final_k",
        "retrieval.langgraph_max_query_rewrites",
        "retrieval.multi_query_m",
        "retrieval.topk_dense",
        "retrieval.topk_sparse",
        "scoring.filename_boost_exact",
        "scoring.filename_boost_partial",
        "sparse_search.top_k",
        "tracing.alert_webhook_timeout",
        "tracing.trace_retention",
        "vector_search.top_k",
    }
)


def test_every_number_field_advertises_its_pydantic_bounds() -> None:
    """A NumberField's min/max ARE its clamp, so they may not disagree with the model.

    `NumberField` reads the bounds back off the rendered element and forces the committed value
    inside them before the store ever sees it. A UI bound narrower than the model silently
    refuses a legal value (this caught embedding.late_chunking_max_doc_tokens advertising
    min=512 against ge=256); a wider one sends a value the PATCH rejects as a 422 with no field
    attribution, surfaced only as a generic store error.

    This is the general form of the per-field literal assertions above: every numeric config
    control in the app, checked against the field it writes.
    """
    sources = sorted((ROOT / "web/src").rglob("*.tsx"))
    assert sources, "no frontend sources found"

    checked = 0
    problems: dict[str, list[str]] = {}
    for path in sources:
        source = path.read_text(encoding="utf-8")
        if "<NumberField" not in source:
            continue
        bindings = dict(
            re.findall(
                r"const \[\s*(\w+),\s*set\w+\s*\]\s*=\s*\n?\s*useConfigField<number>\(\s*\n?\s*'([\w.]+)'",
                source,
            )
        )
        rel = path.relative_to(ROOT)
        for element in _jsx_elements(source, "NumberField"):
            value_prop = re.search(r"value=\{([^\n]*)", element)
            assert value_prop is not None, f"{rel}: a NumberField has no value prop"
            # One control reads `value={a || b}`, so take the first identifier in the expression
            # that is a config binding rather than requiring a bare variable.
            candidates = [n for n in re.findall(r"\w+", value_prop.group(1)) if n in bindings]
            assert candidates, (
                f"{rel}: NumberField value={value_prop.group(1)!r} writes no "
                "useConfigField<number> binding"
            )
            config_path = bindings[candidates[0]]
            low, high = _config_field_bounds(config_path)
            ui_min = re.search(r"min=\{(-?[\d_.]+)\}", element)
            ui_max = re.search(r"max=\{(-?[\d_.]+)\}", element)
            got_min = float(ui_min.group(1).replace("_", "")) if ui_min else None
            got_max = float(ui_max.group(1).replace("_", "")) if ui_max else None
            checked += 1
            found: list[str] = []
            if (low is None) != (got_min is None) or (
                low is not None and got_min != float(low)
            ):
                found.append(f"min={got_min} vs ge={low}")
            if (high is None) != (got_max is None) or (
                high is not None and got_max != float(high)
            ):
                found.append(f"max={got_max} vs le={high}")
            if found:
                problems.setdefault(config_path, []).extend(f"{rel}: {config_path} {f}" for f in found)

    assert checked >= 45, f"expected to check every numeric config control, checked {checked}"

    unexpected = sorted(set(problems) - KNOWN_NUMBER_FIELD_BOUND_GAPS)
    assert not unexpected, "new NumberField bounds disagree with the config model:\n  " + "\n  ".join(
        detail for path in unexpected for detail in problems[path]
    )

    fixed = sorted(KNOWN_NUMBER_FIELD_BOUND_GAPS - set(problems))
    assert not fixed, (
        "these bounds now match the model -- remove them from KNOWN_NUMBER_FIELD_BOUND_GAPS: "
        + ", ".join(fixed)
    )


def test_no_config_editor_still_writes_a_raw_number_input() -> None:
    """Raw `<input type="number">` clamped nothing and wrote on every keystroke.

    The two config editors are the whole numeric-config surface; a new raw numeric input here
    is a field that bypasses the shared commit-on-blur clamp, which is how out-of-range values
    reached the PATCH in the first place.
    """
    for relative in ("web/src/components/RAG/IndexingSubtab.tsx", "web/src/components/RAG/RetrievalSubtab.tsx"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'type="number"' not in source, (
            f"{relative} still has a raw numeric input; use NumberField so the value is clamped "
            "to its Pydantic bounds on commit"
        )
