"""Tests for the OSS config and secret control plane registry."""

from server.config_control_plane import (
    _UNIT_SUFFIXES,
    _label_for_path,
    build_config_field_descriptors,
    list_config_leaf_paths,
    validate_config_field_registry,
    validate_integration_contracts,
    validate_secret_registry,
)


def test_config_control_plane_registry_covers_all_leaf_paths_once() -> None:
    leaf_paths = list_config_leaf_paths()
    descriptors = build_config_field_descriptors()
    descriptor_paths = [descriptor.path for descriptor in descriptors]

    assert descriptor_paths == sorted(descriptor_paths)
    assert len(descriptor_paths) == len(set(descriptor_paths))
    assert set(descriptor_paths) == set(leaf_paths)


def test_config_control_plane_registry_has_no_validation_errors() -> None:
    assert validate_config_field_registry() == []
    assert validate_secret_registry() == []
    assert validate_integration_contracts() == []


def test_a_trailing_unit_suffix_is_rendered_as_a_unit_not_a_word() -> None:
    """`indexing.figures.timeout_s` used to read "Timeout S" (M-160/A-42)."""
    assert _label_for_path("indexing.figures.timeout_s") == "Timeout (seconds)"
    assert _label_for_path("eval.ragas_judge_timeout_s") == "Ragas Judge Timeout (seconds)"
    assert _label_for_path("observability.latency_ms") == "Latency (milliseconds)"
    assert _label_for_path("indexing.index_max_file_size_mb") == "Index Max File Size (MB)"
    assert _label_for_path("ui.learning_reranker_studio_left_panel_pct") == (
        "Learning Reranker Studio Left Panel (%)"
    )
    assert _label_for_path("cost.estimated_cost_usd") == "Estimated Cost (USD)"


def test_a_unit_word_that_is_not_a_suffix_stays_a_word() -> None:
    """Only the LAST segment is a unit; the acronym table still wins for real acronyms."""
    # A single-segment leaf has no unit to strip.
    assert _label_for_path("retrieval.s") == "S"
    # Mid-name occurrences are names, not units.
    assert _label_for_path("retrieval.ms_between_retries") == "Ms Between Retries"
    assert _label_for_path("tracing.otlp_endpoint") == "OTLP Endpoint"


def test_no_registry_label_ends_in_a_bare_unit_abbreviation() -> None:
    """A tree invariant: one stray unit suffix anywhere in the registry fails this."""
    stray = [
        descriptor.path
        for descriptor in build_config_field_descriptors()
        if descriptor.label.split(" ")[-1].lower() in _UNIT_SUFFIXES
    ]
    assert stray == [], f"labels ending in a bare unit abbreviation: {stray}"
