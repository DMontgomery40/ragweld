"""Validate the glossary consumed by real UI help, without network or API mocks."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]


def test_glossary_records_and_reference_contract() -> None:
    source = ROOT / "data/glossary.json"
    assert source.read_bytes() == (ROOT / "web/public/glossary.json").read_bytes()
    terms = json.loads(source.read_text())["terms"]
    keys = [term["key"] for term in terms]
    assert len(keys) == len(set(keys)), "Glossary keys must be unique"
    for term in terms:
        for field in ("key", "term", "definition", "category"):
            assert isinstance(term[field], str) and term[field].strip(), (term["key"], field)
        assert isinstance(term["related"], list)
        assert all(isinstance(key, str) and key.strip() for key in term["related"])
        for link in term.get("links", []):
            assert isinstance(link["text"], str) and link["text"].strip(), term["key"]
            parsed = urlsplit(link["href"])
            assert parsed.scheme == "https" and parsed.netloc, (term["key"], link)
            assert not parsed.username and not parsed.password, (term["key"], link)


def test_literal_tooltip_names_resolve_in_glossary() -> None:
    keys = {term["key"] for term in json.loads((ROOT / "data/glossary.json").read_text())["terms"]}
    # Covers both JSX string attributes and expression string literals. Dynamic
    # maps remain part of the explicit source inventory, not a regex completeness claim.
    pattern = re.compile(r"<TooltipIcon\b[^>]*?\bname\s*=\s*\{?\s*(['\"])(.*?)\1", re.DOTALL)
    missing = []
    for source in (ROOT / "web/src").rglob("*.tsx"):
        for match in pattern.finditer(source.read_text()):
            if match[2] not in keys:
                missing.append((str(source.relative_to(ROOT)), match[2]))
    assert not missing, missing


def test_every_config_explorer_field_has_explicit_glossary_help() -> None:
    from server.config_control_plane import build_config_field_descriptors

    mapping = json.loads((ROOT / "web/src/components/Admin/configGlossaryKeys.json").read_text())
    fields = {field.path for field in build_config_field_descriptors()}
    assert set(mapping) == fields, {
        "missing": sorted(fields - set(mapping)),
        "obsolete": sorted(set(mapping) - fields),
    }
    terms = {term["key"]: term for term in json.loads((ROOT / "data/glossary.json").read_text())["terms"]}
    for path, key in mapping.items():
        assert key in terms, (path, key)
        assert "No detailed tooltip available" not in terms[key]["definition"], (path, key)
