from __future__ import annotations

import json
from pathlib import Path

from server.models.tribrid_config_model import ChatConfig, SystemPromptsConfig, TrainingConfig


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
        "tests/integration/test_pg_search_bm25.py",
        "tests/unit/test_synthetic_sdkit_provider.py",
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
