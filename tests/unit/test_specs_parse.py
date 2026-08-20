from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_all_yaml_specs_parse_as_mappings() -> None:
    spec_paths = sorted((ROOT / "spec").rglob("*.yaml"))

    assert spec_paths
    for path in spec_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), path.relative_to(ROOT)
