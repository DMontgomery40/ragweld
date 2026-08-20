from __future__ import annotations

from pathlib import Path

from scripts.check_banned import check_typescript_files


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_public_wire_interfaces_are_rejected_but_local_view_types_are_allowed(tmp_path) -> None:
    web_src = tmp_path / "web/src"
    _write(
        tmp_path,
        "web/src/api/example.ts",
        "export interface FooResponse { value: string }\n",
    )
    _write(
        tmp_path,
        "web/src/components/Example.tsx",
        "interface FooConfig { dense: boolean }\ninterface FooViewModel { label: string }\n",
    )

    errors = check_typescript_files(web_src=web_src)

    assert len(errors) == 1
    assert "public wire interface" in errors[0]
    assert "FooConfig" not in errors[0]


def test_generated_wire_import_is_allowed(tmp_path) -> None:
    web_src = tmp_path / "web/src"
    _write(
        tmp_path,
        "web/src/api/example.ts",
        "import type { SearchResponse } from '../types/generated'\n",
    )

    assert check_typescript_files(web_src=web_src) == []
