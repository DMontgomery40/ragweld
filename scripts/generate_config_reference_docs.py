#!/usr/bin/env python3
"""
Generate MkDocs configuration reference from Pydantic models.

Source of truth:
  - server/models/tribrid_config_model.py :: TriBridConfig (nested config)
  - data/glossary.json :: long-form tooltip definitions (by env-style key)

Output:
  - mkdocs/docs/reference/config/index.md
  - mkdocs/docs/reference/config/<section>.md (one per top-level TriBridConfig section)
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

ROOT = Path(__file__).resolve().parents[1]
CONFIG_MODEL_PATH = ROOT / "server" / "models" / "tribrid_config_model.py"
GLOSSARY_PATH = ROOT / "data" / "glossary.json"
DEFAULT_OUT_DIR = ROOT / "mkdocs" / "docs" / "reference" / "config"


def _md_escape_table_cell(s: str) -> str:
    # Keep tables stable (pipes break rendering).
    return (s or "").replace("|", "\\|").replace("\n", "<br>")


def _indent_md(s: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else "" for line in (s or "").splitlines())


def _safe_json(v: Any) -> str:
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return json.dumps(str(v), ensure_ascii=False)


def _type_str(tp: Any) -> str:
    if tp is None:
        return "None"

    origin = get_origin(tp)
    args = get_args(tp)

    if origin is None:
        if isinstance(tp, type):
            return tp.__name__
        return str(tp).replace("typing.", "")

    if origin in (list, set, tuple):
        inner = _type_str(args[0]) if args else "Any"
        return f"{origin.__name__}[{inner}]"

    if origin is dict:
        k = _type_str(args[0]) if len(args) > 0 else "Any"
        v = _type_str(args[1]) if len(args) > 1 else "Any"
        return f"dict[{k}, {v}]"

    if str(origin).endswith("Literal"):
        return "Literal[" + ", ".join(_safe_json(a) for a in args) + "]"

    if origin is Optional or str(origin).endswith("Union"):
        # Optional[T] is Union[T, NoneType]
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(args) == 2:
            return f"{_type_str(non_none[0])} | None"
        return " | ".join(_type_str(a) for a in args)

    return str(tp).replace("typing.", "")


def _literal_values(tp: Any) -> list[str]:
    origin = get_origin(tp)
    if origin is None:
        return []
    if str(origin).endswith("Literal"):
        return [_safe_json(a) for a in get_args(tp)]
    return []


def _is_model_type(tp: Any) -> Optional[type[BaseModel]]:
    """Return the BaseModel subclass if `tp` is (or wraps) one, else None."""

    if tp is None:
        return None

    origin = get_origin(tp)
    args = get_args(tp)

    candidates: list[Any] = []
    if origin is None:
        candidates = [tp]
    elif origin is Optional or str(origin).endswith("Union"):
        candidates = [a for a in args if a is not type(None)]  # noqa: E721
    else:
        return None

    for c in candidates:
        try:
            if isinstance(c, type) and issubclass(c, BaseModel):
                return c
        except Exception:
            continue
    return None


def _constraints_str(field: Any) -> str:
    # Pydantic v2 encodes constraints in FieldInfo.metadata.
    parts: list[str] = []

    for m in getattr(field, "metadata", []) or []:
        cls_name = m.__class__.__name__

        # annotated_types (Ge/Le/Gt/Lt/MultipleOf/etc.)
        for attr, label in (
            ("ge", "≥"),
            ("gt", ">"),
            ("le", "≤"),
            ("lt", "<"),
            ("multiple_of", "multiple_of"),
        ):
            if hasattr(m, attr):
                val = getattr(m, attr)
                if val is not None:
                    if label in {"≥", ">", "≤", "<"}:
                        parts.append(f"{label} {val}")
                    else:
                        parts.append(f"{label}={val}")

        # String constraints (MinLen/MaxLen, regex/pattern)
        if cls_name in {"MinLen", "MaxLen"}:
            if hasattr(m, "min_length"):
                parts.append(f"min_length={getattr(m, 'min_length')}")
            if hasattr(m, "max_length"):
                parts.append(f"max_length={getattr(m, 'max_length')}")

        if hasattr(m, "pattern") and getattr(m, "pattern"):
            parts.append(f"pattern={getattr(m, 'pattern')}")

    # Literal allowed values
    lit = _literal_values(getattr(field, "annotation", None))
    if lit:
        parts.append("allowed=" + ", ".join(lit))

    return ", ".join(parts)


def _default_value_from_instance(instance: Any, field_name: str) -> Any:
    if instance is None:
        return None
    try:
        return getattr(instance, field_name)
    except Exception:
        return None


def _default_str(field: Any, instance_value: Any) -> str:
    if instance_value is not None:
        if isinstance(instance_value, BaseModel):
            return f"<{instance_value.__class__.__name__}>"
        return _safe_json(instance_value)

    default = getattr(field, "default", PydanticUndefined)
    if default is not PydanticUndefined:
        if isinstance(default, BaseModel):
            return f"<{default.__class__.__name__}>"
        return _safe_json(default)

    if getattr(field, "default_factory", None) is not None:
        return "<factory>"

    return "(required)"


@dataclass(frozen=True)
class GlossaryTerm:
    key: str
    term: str
    definition: str
    category: str | None
    badges: list[dict[str, Any]]
    links: list[dict[str, Any]]


def load_glossary() -> dict[str, GlossaryTerm]:
    data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    out: dict[str, GlossaryTerm] = {}
    for t in data.get("terms", []) or []:
        key = t.get("key")
        if not key:
            continue
        out[str(key)] = GlossaryTerm(
            key=str(key),
            term=str(t.get("term") or ""),
            definition=str(t.get("definition") or ""),
            category=(str(t.get("category")) if t.get("category") is not None else None),
            badges=list(t.get("badges") or []),
            links=list(t.get("links") or []),
        )
    return out


def _attr_chain(node: ast.AST) -> Optional[list[str]]:
    # self.foo.bar -> ["self", "foo", "bar"]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        base = _attr_chain(node.value)
        if not base:
            return None
        return base + [node.attr]
    return None


def load_env_key_mapping() -> dict[str, list[str]]:
    """Build mapping: 'retrieval.rrf_k_div' -> ['RRF_K_DIV', ...] from TriBridConfig.to_flat_dict()."""

    tree = ast.parse(CONFIG_MODEL_PATH.read_text(encoding="utf-8"))
    path_to_keys: dict[str, list[str]] = {}

    class_node: Optional[ast.ClassDef] = None
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == "TriBridConfig":
            class_node = n
            break

    if class_node is None:
        return {}

    fn: Optional[ast.FunctionDef] = None
    for n in class_node.body:
        if isinstance(n, ast.FunctionDef) and n.name == "to_flat_dict":
            fn = n
            break

    if fn is None:
        return {}

    dict_node: Optional[ast.Dict] = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            dict_node = n.value
            break

    if dict_node is None:
        return {}

    for k_node, v_node in zip(dict_node.keys, dict_node.values):
        if not isinstance(k_node, ast.Constant) or not isinstance(k_node.value, str):
            continue
        key = k_node.value.strip()
        chain = _attr_chain(v_node)
        if not chain or not chain or chain[0] != "self":
            continue
        # self.retrieval.rrf_k_div -> retrieval.rrf_k_div
        dotted = ".".join(chain[1:])
        if not dotted:
            continue
        path_to_keys.setdefault(dotted, []).append(key)

    # Stabilize ordering
    for p, keys in list(path_to_keys.items()):
        path_to_keys[p] = sorted(set(keys))

    return path_to_keys


@dataclass
class FieldEntry:
    json_key: str
    env_keys: list[str]
    type_str: str
    default_str: str
    constraints: str
    summary: str
    glossary: GlossaryTerm | None


def _flatten_model(
    *,
    model_cls: type[BaseModel],
    instance: BaseModel,
    prefix: str,
    env_map: dict[str, list[str]],
    glossary: dict[str, GlossaryTerm],
) -> list[FieldEntry]:
    entries: list[FieldEntry] = []

    for name, field in model_cls.model_fields.items():
        ann = getattr(field, "annotation", None)
        child_model = _is_model_type(ann)
        full_path = f"{prefix}.{name}" if prefix else name

        if child_model is not None:
            child_instance = _default_value_from_instance(instance, name)
            if not isinstance(child_instance, BaseModel):
                try:
                    child_instance = child_model()
                except Exception:
                    child_instance = None
            if isinstance(child_instance, BaseModel):
                entries.extend(
                    _flatten_model(
                        model_cls=child_model,
                        instance=child_instance,
                        prefix=full_path,
                        env_map=env_map,
                        glossary=glossary,
                    )
                )
            continue

        env_keys = env_map.get(full_path, [])
        g: GlossaryTerm | None = None
        for k in env_keys:
            if k in glossary:
                g = glossary[k]
                break

        summary = (getattr(field, "description", None) or "").strip()
        if not summary and g is not None:
            summary = g.term.strip()

        instance_value = _default_value_from_instance(instance, name)
        entries.append(
            FieldEntry(
                json_key=full_path,
                env_keys=env_keys,
                type_str=_type_str(ann),
                default_str=_default_str(field, instance_value),
                constraints=_constraints_str(field),
                summary=summary,
                glossary=g,
            )
        )

    # Sort by json key for stability
    entries.sort(key=lambda e: e.json_key)
    return entries


def _section_title(section: str) -> str:
    return f"Config reference: `{section}`"


def _write_config_index(
    *,
    out_dir: Path,
    sections: list[tuple[str, type[BaseModel]]],
) -> None:
    lines: list[str] = []
    lines.append("# Configuration Reference")
    lines.append("")
    lines.append('<div class="grid chunk_summaries" markdown>')
    lines.append("")
    lines.append('-   :material-file-cog:{ .lg .middle } **Generated from Pydantic**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    Every knob comes from `server/models/tribrid_config_model.py` — defaults and constraints included.")
    lines.append("")
    lines.append('-   :material-tooltip-text:{ .lg .middle } **Glossary-backed**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    Long-form tuning guidance is pulled from `data/glossary.json` when available.")
    lines.append("")
    lines.append('-   :material-magnify:{ .lg .middle } **Searchable**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    Use site search to jump to any parameter by JSON key or env-style key.")
    lines.append("")
    lines.append("</div>")
    lines.append("")
    lines.append("[Config API & workflow](../../configuration.md){ .md-button .md-button--primary }")
    lines.append("[Glossary](../../glossary.md){ .md-button }")
    lines.append("[User manual](../../manual/index.md){ .md-button }")
    lines.append("")
    lines.append('!!! note "Auto-generated"')
    lines.append(
        "    These pages are generated. To update them, modify the Pydantic config model and/or glossary, then re-run the generator script."
    )
    lines.append("")
    lines.append("## Sections")
    lines.append("")
    lines.append("| Section | Page |")
    lines.append("|---------|------|")
    for name, _cls in sections:
        lines.append(f"| `{name}` | [`{name}.md`]({name}.md) |")
    lines.append("")
    (out_dir / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_section_page(
    *,
    out_dir: Path,
    section: str,
    entries: list[FieldEntry],
) -> None:
    title = _section_title(section)

    parent_paths: dict[str, list[FieldEntry]] = {}
    for e in entries:
        rel = e.json_key.removeprefix(section + ".") if e.json_key.startswith(section + ".") else e.json_key
        parent = ".".join(rel.split(".")[:-1]) or "(root)"
        parent_paths.setdefault(parent, []).append(e)

    # Stable group ordering
    group_names = sorted(parent_paths.keys(), key=lambda s: (s != "(root)", s))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append('<div class="grid chunk_summaries" markdown>')
    lines.append("")
    lines.append('-   :material-tune:{ .lg .middle } **Enterprise tuning surface**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    Defaults + constraints are rendered directly from Pydantic.")
    lines.append("")
    lines.append('-   :material-key-outline:{ .lg .middle } **Env keys when available**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).")
    lines.append("")
    lines.append('-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**')
    lines.append("")
    lines.append("    ---")
    lines.append("")
    lines.append("    If a matching glossary entry exists, you’ll see deeper tuning notes.")
    lines.append("")
    lines.append("</div>")
    lines.append("")
    lines.append("[Config reference](index.md){ .md-button .md-button--primary }")
    lines.append("[Config API & workflow](../../configuration.md){ .md-button }")
    lines.append("[Glossary](../../glossary.md){ .md-button }")
    lines.append("")
    lines.append(f"**Total parameters**: {len(entries)}")
    lines.append("")
    lines.append('??? info "Group index"')
    lines.append(_indent_md("\n".join(f"- `{g}`" for g in group_names)))
    lines.append("")

    for g in group_names:
        lines.append(f"## `{g}`")
        lines.append("")
        lines.append("| JSON key | Env key(s) | Type | Default | Constraints | Summary |")
        lines.append("|---------|------------|------|---------|-------------|---------|")
        for e in parent_paths[g]:
            env = ", ".join(f"`{k}`" for k in e.env_keys) if e.env_keys else "—"
            constraints = e.constraints or "—"
            summary = e.summary or "—"
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{e.json_key}`",
                        env,
                        f"`{_md_escape_table_cell(e.type_str)}`",
                        f"`{_md_escape_table_cell(e.default_str)}`",
                        _md_escape_table_cell(constraints),
                        _md_escape_table_cell(summary),
                    ]
                )
                + " |"
            )
        lines.append("")

        # Tooltip-level details (from glossary) for this group
        details = [e for e in parent_paths[g] if e.glossary is not None and e.env_keys]
        if details:
            lines.append("### Details (glossary)")
            lines.append("")
            for e in details:
                term = e.glossary
                env_key = next((k for k in e.env_keys if k == term.key), e.env_keys[0])
                heading = f"`{e.json_key}` (`{env_key}`)"
                if term.term:
                    heading += f" — {term.term}"
                lines.append(f'??? info "{heading}"')
                body_lines: list[str] = []
                if term.category:
                    body_lines.append(f"**Category**: `{term.category}`")
                    body_lines.append("")
                if term.definition:
                    body_lines.append(term.definition.rstrip())
                    body_lines.append("")
                if term.badges:
                    body_lines.append("**Badges**:")
                    for b in term.badges:
                        body_lines.append(f"- {b.get('text', '')}".rstrip())
                    body_lines.append("")
                if term.links:
                    body_lines.append("**Links**:")
                    for link in term.links:
                        txt = (link.get('text') or '').strip()
                        href = (link.get('href') or '').strip()
                        if txt and href:
                            body_lines.append(f"- [{txt}]({href})")
                    body_lines.append("")
                lines.append(_indent_md("\n".join(body_lines).rstrip()))
                lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    (out_dir / f"{section}.md").write_text(content, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate MkDocs config reference from Pydantic")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory under mkdocs/docs/")
    ap.add_argument("--clean", action="store_true", help="Delete existing .md files in the output directory first")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for p in out_dir.glob("*.md"):
            p.unlink()

    glossary = load_glossary()
    env_map = load_env_key_mapping()

    # Import here so script can be imported without server deps in tooling.
    from server.models.tribrid_config_model import TriBridConfig  # noqa: WPS433

    root = TriBridConfig()
    sections: list[tuple[str, type[BaseModel]]] = []
    for section_name, field in TriBridConfig.model_fields.items():
        section_cls = _is_model_type(getattr(field, "annotation", None))
        if section_cls is None:
            continue
        sections.append((section_name, section_cls))

    sections.sort(key=lambda t: t[0])
    _write_config_index(out_dir=out_dir, sections=sections)

    for section_name, section_cls in sections:
        section_instance = getattr(root, section_name)
        entries = _flatten_model(
            model_cls=section_cls,
            instance=section_instance,
            prefix=section_name,
            env_map=env_map,
            glossary=glossary,
        )
        _write_section_page(
            out_dir=out_dir,
            section=section_name,
            entries=entries,
        )

    print(f"Wrote config reference: {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

