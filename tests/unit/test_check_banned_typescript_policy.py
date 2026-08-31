from __future__ import annotations

from pathlib import Path

from scripts.check_banned import check_typescript_files, check_zero_mock_tests


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


def _mock_scan(tmp_path: Path, relative: str, content: str) -> list[str]:
    """Run the pytest-mock half of the checker over one fixture file only."""
    _write(tmp_path, relative, content)
    return check_zero_mock_tests(
        web_tests_root=tmp_path / ".tests-none",
        pytests_root=tmp_path / "tests",
    )


def test_httpx_client_patch_is_not_a_mock(tmp_path) -> None:
    # A PATCH request through an httpx client is not `unittest.mock.patch`.
    errors = _mock_scan(
        tmp_path,
        "tests/api/test_thing.py",
        'async def test_it(client):\n    r = await client.patch("/api/config/x", json={})\n',
    )
    assert errors == [], errors


def test_bare_patch_call_is_flagged(tmp_path) -> None:
    errors = _mock_scan(
        tmp_path,
        "tests/api/test_thing.py",
        'def test_it():\n    with patch("server.x.y") as m:\n        m()\n',
    )
    assert len(errors) == 1
    assert "patch()" in errors[0]


def test_unittest_import_mock_forms_are_flagged(tmp_path) -> None:
    # `from unittest import mock` and the third-party `import mock` were matched by
    # no rule before; both are mock usage and must be caught at the import.
    from_unittest = _mock_scan(
        tmp_path,
        "tests/unit/test_a.py",
        "from unittest import mock\n\n\ndef test_a():\n    mock.patch('x')\n",
    )
    assert any("unittest.mock" in e for e in from_unittest), from_unittest

    bare_import = _mock_scan(
        tmp_path,
        "tests/unit/test_b.py",
        "import mock\n\n\ndef test_b():\n    mock.MagicMock()\n",
    )
    assert any("mock" in e.lower() for e in bare_import), bare_import
