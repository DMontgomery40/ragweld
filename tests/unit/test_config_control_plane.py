"""Tests for the OSS config and secret control plane registry."""

from server.config_control_plane import (
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
