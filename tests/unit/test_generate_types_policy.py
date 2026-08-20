from __future__ import annotations

from scripts import generate_types


def test_generated_header_describes_registered_wire_contract_boundary(tmp_path) -> None:
    output = tmp_path / "generated.ts"
    generate_types.main(output_path=output)
    header = output.read_text(encoding="utf-8")[:1400]

    assert "registered public API and configuration boundary" in header
    assert "Local UI state and view models may be handwritten" in header
    assert "THE LAW" not in header
    assert "after ANY" not in header
