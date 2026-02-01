#!/usr/bin/env python3
"""Generate TypeScript types from Pydantic models.

This script is THE ENFORCEMENT MECHANISM for the Pydantic-first architecture.
Run this after ANY change to server/models/tribrid_config_model.py.

Usage:
    uv run scripts/generate_types.py

The generated file (web/src/types/generated.ts) should NEVER be edited by hand.
All TypeScript types for API data MUST be imported from generated.ts.
"""
import json
import sys
from pathlib import Path
from typing import Any


def json_type_to_ts(json_type: str | list[str], format_hint: str | None = None) -> str:
    """Convert JSON Schema type to TypeScript type."""
    if isinstance(json_type, list):
        # Union type - handle null
        types = [json_type_to_ts(t) for t in json_type if t != "null"]
        has_null = "null" in json_type
        result = " | ".join(types) if len(types) > 1 else types[0] if types else "unknown"
        if has_null:
            result = f"{result} | null"
        return result

    type_map = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
        "object": "Record<string, unknown>",
        "array": "unknown[]",
    }
    return type_map.get(json_type, "unknown")


def resolve_ref(ref: str, definitions: dict[str, Any]) -> str:
    """Resolve a $ref to a TypeScript type name."""
    # $ref format: "#/$defs/TypeName" or "#/definitions/TypeName"
    if ref.startswith("#/$defs/"):
        return ref.replace("#/$defs/", "")
    if ref.startswith("#/definitions/"):
        return ref.replace("#/definitions/", "")
    return "unknown"


def property_to_ts_type(prop: dict[str, Any], definitions: dict[str, Any]) -> str:
    """Convert a JSON Schema property to TypeScript type."""
    # Handle $ref
    if "$ref" in prop:
        return resolve_ref(prop["$ref"], definitions)

    # Handle anyOf (union types, often for optional)
    if "anyOf" in prop:
        types = []
        for item in prop["anyOf"]:
            if "$ref" in item:
                types.append(resolve_ref(item["$ref"], definitions))
            elif item.get("type") == "null":
                types.append("null")
            else:
                types.append(property_to_ts_type(item, definitions))
        return " | ".join(types)

    # Handle allOf (intersection types)
    if "allOf" in prop:
        types = [property_to_ts_type(item, definitions) for item in prop["allOf"]]
        return " & ".join(types)

    # Handle oneOf
    if "oneOf" in prop:
        types = [property_to_ts_type(item, definitions) for item in prop["oneOf"]]
        return " | ".join(types)

    # Handle enum
    if "enum" in prop:
        return " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in prop["enum"])

    # Handle const
    if "const" in prop:
        v = prop["const"]
        return f'"{v}"' if isinstance(v, str) else str(v)

    # Handle arrays
    if prop.get("type") == "array":
        if "items" in prop:
            item_type = property_to_ts_type(prop["items"], definitions)
            return f"{item_type}[]"
        return "unknown[]"

    # Handle objects with additionalProperties (Record types)
    if prop.get("type") == "object":
        if "additionalProperties" in prop:
            additional_props = prop["additionalProperties"]
            # additionalProperties can be a boolean or a schema
            if isinstance(additional_props, bool):
                return "Record<string, unknown>" if additional_props else "Record<string, never>"
            value_type = property_to_ts_type(additional_props, definitions)
            return f"Record<string, {value_type}>"
        if "properties" in prop:
            # Inline object type
            return "{ " + "; ".join(
                f"{k}: {property_to_ts_type(v, definitions)}"
                for k, v in prop["properties"].items()
            ) + " }"
        return "Record<string, unknown>"

    # Handle basic types
    if "type" in prop:
        return json_type_to_ts(prop["type"], prop.get("format"))

    return "unknown"


def definition_to_interface(name: str, definition: dict[str, Any], definitions: dict[str, Any]) -> str:
    """Convert a JSON Schema definition to TypeScript interface."""
    lines = []

    # Add JSDoc comment if description exists
    if "description" in definition:
        # Handle multi-line descriptions
        desc = definition['description'].replace('\n', ' ').strip()
        lines.append(f"/** {desc} */")

    properties = definition.get("properties", {})
    required = set(definition.get("required", []))

    if not properties:
        # Type alias for simple types
        if "enum" in definition:
            enum_values = " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in definition["enum"])
            lines.append(f"export type {name} = {enum_values};")
        elif "type" in definition:
            lines.append(f"export type {name} = {json_type_to_ts(definition['type'])};")
        else:
            lines.append(f"export interface {name} {{}}")
        return "\n".join(lines)

    lines.append(f"export interface {name} {{")

    for prop_name, prop_def in properties.items():
        # Add property comment
        if "description" in prop_def:
            desc = prop_def["description"].replace("\n", " ").strip()
            lines.append(f"  /** {desc} */")

        # Determine if optional
        optional = prop_name not in required
        optional_marker = "?" if optional else ""

        # Get TypeScript type
        ts_type = property_to_ts_type(prop_def, definitions)

        # Add default value as comment if present
        default_comment = ""
        if "default" in prop_def:
            default_val = prop_def["default"]
            if isinstance(default_val, str):
                # Truncate long string defaults
                if len(default_val) > 50:
                    default_comment = f' // default: "{default_val[:47]}..."'
                else:
                    default_comment = f' // default: "{default_val}"'
            elif isinstance(default_val, (dict, list)):
                json_str = json.dumps(default_val)
                if len(json_str) > 50:
                    default_comment = f" // default: {json_str[:47]}..."
                else:
                    default_comment = f" // default: {json_str}"
            else:
                default_comment = f" // default: {default_val}"

        lines.append(f"  {prop_name}{optional_marker}: {ts_type};{default_comment}")

    lines.append("}")
    return "\n".join(lines)


def generate_root_interface(name: str, schema: dict[str, Any], definitions: dict[str, Any]) -> str:
    """Generate TypeScript interface for a root model (not just $defs)."""
    lines = []

    # Add JSDoc comment
    if "description" in schema:
        desc = schema['description'].replace('\n', ' ').strip()
        lines.append(f"/** {desc} */")

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return f"export interface {name} {{}}"

    lines.append(f"export interface {name} {{")

    for prop_name, prop_def in properties.items():
        if "description" in prop_def:
            desc = prop_def["description"].replace("\n", " ").strip()
            lines.append(f"  /** {desc} */")

        optional = prop_name not in required
        optional_marker = "?" if optional else ""
        ts_type = property_to_ts_type(prop_def, definitions)

        lines.append(f"  {prop_name}{optional_marker}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    """Generate TypeScript types from Pydantic models."""
    print("=" * 60)
    print("GENERATING TYPESCRIPT TYPES FROM PYDANTIC MODELS")
    print("=" * 60)

    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    output_path = project_root / "web" / "src" / "types" / "generated.ts"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("\nSource: server.models.tribrid_config_model")
    print(f"Output: {output_path}\n")

    try:
        # Import all models from THE LAW
        from server.models.tribrid_config_model import (  # noqa: I001
            # Root config
            TriBridConfig,
            # Domain models - Index
            Chunk,
            IndexRequest,
            IndexStatus,
            IndexStats,
            # Domain models - Dashboard index summary
            DashboardIndexStorageBreakdown,
            DashboardEmbeddingConfigSummary,
            DashboardIndexCosts,
            DashboardIndexStatusMetadata,
            DashboardIndexStatusResponse,
            DashboardIndexStatsResponse,
            # Domain models - Dev stack orchestration (local dev only)
            DevStackStatusResponse,
            DevStackRestartResponse,
            # Domain models - Corpora
            Corpus,
            CorpusCreateRequest,
            CorpusUpdateRequest,
            CorpusStats,
            # Domain models - Index tooling
            VocabPreviewTerm,
            VocabPreviewResponse,
            # Domain models - Chunk summaries + keywords
            ChunkSummary,
            ChunkSummariesLastBuild,
            ChunkSummariesResponse,
            ChunkSummariesBuildRequest,
            KeywordsGenerateRequest,
            KeywordsGenerateResponse,
            # Domain models - Retrieval
            ChunkMatch,
            SearchRequest,
            SearchResponse,
            AnswerRequest,
            AnswerResponse,
            # Domain models - Chat
            Message,
            ChatRequest,
            ChatResponse,
            # Domain models - Graph
            Entity,
            Relationship,
            Community,
            GraphStats,
            GraphNeighborsResponse,
            # Domain models - Eval
            EvalDatasetItem,
            EvalRequest,
            EvalTestRequest,
            EvalMetrics,
            EvalDoc,
            EvalResult,
            EvalRun,
            EvalRunMeta,
            EvalRunsResponse,
            EvalAnalyzeComparisonResponse,
            EvalComparisonResult,
        )
    except ImportError as e:
        print(f"ERROR: Could not import models: {e}")
        sys.exit(1)

    # Collect all model schemas
    all_models = [
        # Root config
        TriBridConfig,
        # Domain models
        Chunk,
        IndexRequest,
        IndexStatus,
        IndexStats,
        DashboardIndexStorageBreakdown,
        DashboardEmbeddingConfigSummary,
        DashboardIndexCosts,
        DashboardIndexStatusMetadata,
        DashboardIndexStatusResponse,
        DashboardIndexStatsResponse,
        DevStackStatusResponse,
        DevStackRestartResponse,
        Corpus,
        CorpusCreateRequest,
        CorpusUpdateRequest,
        CorpusStats,
        VocabPreviewTerm,
        VocabPreviewResponse,
        ChunkSummary,
        ChunkSummariesLastBuild,
        ChunkSummariesResponse,
        ChunkSummariesBuildRequest,
        KeywordsGenerateRequest,
        KeywordsGenerateResponse,
        ChunkMatch,
        SearchRequest,
        SearchResponse,
        AnswerRequest,
        AnswerResponse,
        Message,
        ChatRequest,
        ChatResponse,
        Entity,
        Relationship,
        Community,
        GraphStats,
        GraphNeighborsResponse,
        EvalDatasetItem,
        EvalRequest,
        EvalTestRequest,
        EvalMetrics,
        EvalDoc,
        EvalResult,
        EvalRun,
        EvalRunMeta,
        EvalRunsResponse,
        EvalAnalyzeComparisonResponse,
        EvalComparisonResult,
    ]

    print(f"Processing {len(all_models)} models...")

    # Merge all definitions from all models
    merged_definitions: dict[str, Any] = {}
    root_schemas: dict[str, dict[str, Any]] = {}

    for model in all_models:
        # Generate schemas in *serialization* mode so TS matches API responses.
        # This matters for the repo_id -> corpus_id migration, where we keep the
        # internal field name `repo_id` but serialize as `corpus_id`.
        schema = model.model_json_schema(mode="serialization", by_alias=True)
        model_name = model.__name__

        # Add definitions from this model's schema
        definitions = schema.get("$defs", schema.get("definitions", {}))
        merged_definitions.update(definitions)

        # Store the root schema for domain models (not just config sub-models)
        # These need their own interface
        root_schemas[model_name] = schema

    print(f"  - Merged {len(merged_definitions)} definitions")
    print(f"  - Processing {len(root_schemas)} root schemas")

    # Generate TypeScript content
    lines: list[str] = []
    generated_names: set[str] = set()

    # First generate all definitions (config sub-models like RetrievalConfig, etc.)
    for name, definition in sorted(merged_definitions.items()):
        if name not in generated_names:
            ts_interface = definition_to_interface(name, definition, merged_definitions)
            lines.append(ts_interface)
            lines.append("")
            generated_names.add(name)

    # Then generate root interfaces for domain models
    # (These are models that aren't just $defs references)
    for model_name, schema in sorted(root_schemas.items()):
        if model_name not in generated_names:
            # Check if this model has its own properties (not just a ref)
            if "properties" in schema:
                ts_interface = generate_root_interface(model_name, schema, merged_definitions)
                lines.append(ts_interface)
                lines.append("")
                generated_names.add(model_name)

    typescript_content = "\n".join(lines)

    # Add header
    header = '''/**
 * AUTO-GENERATED FILE - DO NOT EDIT
 *
 * Generated from: server/models/tribrid_config_model.py
 * Generated by: scripts/generate_types.py
 *
 * To regenerate: uv run scripts/generate_types.py
 *
 * ALL TypeScript types for API data MUST be imported from this file.
 * Hand-writing interfaces that should come from Pydantic is FORBIDDEN.
 *
 * This file contains:
 * - Configuration interfaces (TriBridConfig and sub-configs)
 * - Domain model interfaces (ChunkMatch, SearchRequest, Entity, etc.)
 */

'''

    output_path.write_text(header + typescript_content)

    print("\nSUCCESS! Types generated.")
    print(f"Output: {output_path}")
    print(f"Size: {output_path.stat().st_size} bytes")

    # Count interfaces
    interface_count = typescript_content.count("export interface")
    type_count = typescript_content.count("export type")
    print(f"Interfaces: {interface_count}")
    print(f"Types: {type_count}")
    print(f"Total exports: {interface_count + type_count}")
    print()
    print("Remember: Import from 'types/generated' not hand-written interfaces!")


if __name__ == "__main__":
    main()
