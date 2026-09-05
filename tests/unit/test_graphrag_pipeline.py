from __future__ import annotations

import pytest
from neo4j_graphrag.components.lexical_graph import LexicalGraphBuilder
from neo4j_graphrag.components.types import (
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
)

from server.gateway_reasoning import reasoning_model_params
from server.indexing.code_graph import extract_code_graph, module_id, symbol_id
from server.indexing.graphrag_pipeline import (
    RESERVED_SCOPE_KEYS,
    GraphScopeCollisionError,
    ScopedNeo4jWriter,
    assemble_code_file_graph,
    build_semantic_pipeline,
    chunks_to_text_chunks,
    document_info,
    document_node_id,
    extraction_prompt_template,
    fold_duplicate_node_ids,
    lexical_graph_config,
    require_run_id,
    require_staging_graph_id,
    resolution_property_for_policy,
    run_component_coroutine_in_worker,
    semantic_entity_relation_extractor,
    semantic_extraction_llm,
    stamp_graph_scope,
    validate_no_reserved_scope_keys,
)
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig

RUN_ID = "a" * 32
STAGING_ID = f"__staging__pytest_apollo__{RUN_ID}"


def _graph() -> Neo4jGraph:
    return Neo4jGraph(
        nodes=[
            Neo4jNode(
                id="doc-1",
                label="Document",
                properties={"file_path": "mission.md"},
            ),
            Neo4jNode(
                id="chunk-1",
                label="Chunk",
                properties={
                    "chunk_id": "mission.md:1-4:0",
                    "file_path": "mission.md",
                    "embedding": [0.1, 0.2],
                },
            ),
            Neo4jNode(id="alice", label="Person", properties={"name": "Alice"}),
        ],
        relationships=[
            Neo4jRelationship(
                start_node_id="chunk-1",
                end_node_id="doc-1",
                type="FROM_DOCUMENT",
                properties={},
            ),
            Neo4jRelationship(
                start_node_id="alice",
                end_node_id="chunk-1",
                type="FROM_CHUNK",
                properties={},
            ),
        ],
    )


def test_scope_validators_accept_only_server_staging_ids_and_hex_run_ids() -> None:
    assert require_run_id(RUN_ID) == RUN_ID
    assert require_staging_graph_id(STAGING_ID) == STAGING_ID
    for bad in ("run-1", "A" * 32, "a" * 31, "a" * 33):
        with pytest.raises(ValueError):
            require_run_id(bad)
    for bad in ("apollo", f"__staging__apollo__{'g' * 32}", f"__staging____{RUN_ID}"):
        with pytest.raises(ValueError):
            require_staging_graph_id(bad)


def test_scope_stamp_is_complete_and_removes_chunk_embeddings() -> None:
    graph = _graph()
    lexical = LexicalGraphConfig()
    validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)
    stamp_graph_scope(graph, repo_id=STAGING_ID, run_id=RUN_ID, lexical=lexical)

    assert all(node.properties["repo_id"] == STAGING_ID for node in graph.nodes)
    assert all(node.properties["run_id"] == RUN_ID for node in graph.nodes)
    assert all(rel.properties["repo_id"] == STAGING_ID for rel in graph.relationships)
    assert all(rel.properties["run_id"] == RUN_ID for rel in graph.relationships)

    chunk = next(node for node in graph.nodes if node.label == lexical.chunk_node_label)
    entity = next(node for node in graph.nodes if node.label == "Person")
    document = next(node for node in graph.nodes if node.label == lexical.document_node_label)
    assert chunk.properties["graphJoinId"] == f"{STAGING_ID}:mission.md:1-4:0"
    assert chunk.properties["chunk_id"] == "mission.md:1-4:0"
    assert "embedding" not in chunk.properties
    assert entity.properties["entity_id"] == "alice"
    assert entity.properties["entity_type"] == "Person"
    assert document.properties["file_path"] == "mission.md"


@pytest.mark.parametrize("item_kind", ["node", "relationship"])
@pytest.mark.parametrize("key", ["repo_id", "run_id", "graphJoinId", "__tmp_internal_id"])
def test_reserved_scope_collision_is_rejected_before_stamping(item_kind: str, key: str) -> None:
    graph = _graph()
    if item_kind == "node":
        graph.nodes[0].properties[key] = "attacker"
    else:
        graph.relationships[0].properties[key] = "attacker"
    with pytest.raises(GraphScopeCollisionError, match=item_kind):
        validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)


def test_writer_refuses_a_run_id_that_disagrees_with_the_graph_generation() -> None:
    with pytest.raises(ValueError, match="must match the staging graph generation"):
        ScopedNeo4jWriter(driver=object(), repo_id=STAGING_ID, run_id="b" * 32)


@pytest.mark.asyncio
async def test_worker_component_guard_refuses_the_api_event_loop() -> None:
    async def _component() -> str:
        return "ok"

    with pytest.raises(RuntimeError, match="worker thread"):
        run_component_coroutine_in_worker(_component)


@pytest.mark.parametrize(
    ("model", "base_url", "api_key"),
    [("", "http://gateway/v1", "key"), ("model", "", "key"), ("model", "http://gateway/v1", "")],
)
def test_semantic_pipeline_refuses_an_incomplete_route_before_driver_use(
    model: str, base_url: str, api_key: str
) -> None:
    with pytest.raises(RuntimeError, match="requires"):
        build_semantic_pipeline(
            driver=object(),  # type: ignore[arg-type]
            neo4j_database="neo4j",
            repo_id=STAGING_ID,
            run_id=RUN_ID,
            route_model=model,
            route_base_url=base_url,
            route_api_key=api_key,
            route_upstream="openrouter/openai/gpt-5.6-luna",
            max_concurrency=1,
            llm_timeout_s=30,
            reasoning_effort="medium",
            prompt_template=TriBridConfig().system_prompts.semantic_kg_extraction,
        )


@pytest.mark.parametrize(("policy", "expected"), [("semantic", "name"), ("code", "entity_id")])
def test_resolution_property_follows_the_graph_policy(policy: str, expected: str) -> None:
    """Task 8 drive defect D7: exact-match resolution keyed on ``name`` collapsed every
    ``__init__``/``main`` of the code corpus into one node (81 classes "containing" one
    ``__init__``). A code symbol's identity is its qualified id; a semantic entity's is its
    extracted name.
    """
    assert resolution_property_for_policy(policy) == expected


@pytest.mark.parametrize("policy", ["off", "excluded", ""])
def test_resolution_property_rejects_policies_without_a_graph(policy: str) -> None:
    with pytest.raises(ValueError, match="resolvable graph"):
        resolution_property_for_policy(policy)


@pytest.mark.asyncio
async def test_semantic_extraction_llm_binds_the_operator_timeout_and_reasoning_effort() -> None:
    """Task 8 drive defect D9: the Indexing page offers "Per-chunk timeout (seconds)" and
    "Reasoning effort", but neither reached the extraction LLM - a 5 s timeout with
    ``xhigh`` effort still let a 13 s Luna call promote a graph. The official OpenAILLM
    must carry both: the timeout on its OpenAI clients, the effort in its model params.
    """
    llm = semantic_extraction_llm(
        route_model="openai.gpt-5.6-luna",
        route_base_url="http://127.0.0.1:54000/v1",
        route_api_key="not-a-real-key",
        route_upstream="openrouter/openai/gpt-5.6-luna",
        llm_timeout_s=5,
        reasoning_effort="xhigh",
    )
    try:
        assert llm.model_name == "openai.gpt-5.6-luna"
        # OpenRouter upstream: the effort travels as OpenRouter's native reasoning object (D25).
        assert llm.model_params == {"temperature": 0, "extra_body": {"reasoning": {"effort": "xhigh"}}}
        assert float(llm.async_client.timeout) == 5.0
        assert float(llm.client.timeout) == 5.0
        assert llm.client.max_retries == llm.async_client.max_retries == 0
        assert str(llm.async_client.base_url).rstrip("/") == "http://127.0.0.1:54000/v1"
    finally:
        await llm.aclose()
    assert llm.client.is_closed() and llm.async_client.is_closed()


@pytest.mark.parametrize(
    ("timeout_s", "effort"), [(0, "medium"), (-5, "medium"), (30, ""), (30, "   ")]
)
def test_semantic_extraction_llm_refuses_a_zero_timeout_or_blank_effort(
    timeout_s: int, effort: str
) -> None:
    with pytest.raises(RuntimeError, match="requires"):
        semantic_extraction_llm(
            route_model="openai.gpt-5.6-luna",
            route_base_url="http://127.0.0.1:54000/v1",
            route_api_key="not-a-real-key",
            route_upstream="openrouter/openai/gpt-5.6-luna",
            llm_timeout_s=timeout_s,
            reasoning_effort=effort,
        )


def test_duplicate_extracted_node_ids_are_folded_before_the_official_writer() -> None:
    """Task 8 drive defect D12: the official 1.19 writer CREATEs one node per extracted row,
    so a model response that repeats a node id inside one chunk yields two rows with the same
    chunk-prefixed ``entity_id``; the store's uniqueness constraint then aborted a 2 h Epstein
    run at 99.7 % coverage. Duplicates of the same label fold into the first occurrence
    (properties merged, first value wins). Conflicting identities are refused separately.
    """
    graph = Neo4jGraph(
        nodes=[
            Neo4jNode(id="chunk-1:0", label="Person", properties={"name": "Ada"}),
            Neo4jNode(id="chunk-1:1", label="Person", properties={"name": "Babbage"}),
            Neo4jNode(id="chunk-1:0", label="Person", properties={"name": "Ada", "role": "author"}),
        ],
        relationships=[
            Neo4jRelationship(start_node_id="chunk-1:0", end_node_id="chunk-1:1", type="WROTE_TO"),
        ],
    )
    folded, report = fold_duplicate_node_ids(graph)
    assert [(n.id, n.label) for n in folded.nodes] == [
        ("chunk-1:0", "Person"),
        ("chunk-1:1", "Person"),
    ]
    assert folded.nodes[0].properties == {"name": "Ada", "role": "author"}
    assert [(r.start_node_id, r.end_node_id, r.type) for r in folded.relationships] == [
        ("chunk-1:0", "chunk-1:1", "WROTE_TO")
    ]
    assert report == {"folded_same_label": 1}


def test_unique_extracted_node_ids_pass_through_unchanged() -> None:
    graph = Neo4jGraph(
        nodes=[Neo4jNode(id="c:0", label="Person", properties={"name": "Ada"})],
        relationships=[],
    )
    folded, report = fold_duplicate_node_ids(graph)
    assert folded == graph
    assert report == {"folded_same_label": 0}


@pytest.mark.parametrize(
    ("label", "name"), [("Place", "London"), ("Person", "Babbage")]
)
@pytest.mark.parametrize("occupied_suffix", [False, True])
def test_conflicting_node_identity_is_rejected_without_mutating_input(
    label: str, name: str, occupied_suffix: bool
) -> None:
    nodes = [
        Neo4jNode(id="c:0", label="Person", properties={"name": "Ada"}),
        Neo4jNode(id="c:0", label=label, properties={"name": name}),
    ]
    if occupied_suffix:
        nodes.append(Neo4jNode(id="c:0#2", label="Person", properties={"name": "Grace"}))
    graph = Neo4jGraph(nodes=nodes, relationships=[])
    before = graph.model_dump()
    with pytest.raises(ValueError, match="conflicting identity"):
        fold_duplicate_node_ids(graph)
    assert graph.model_dump() == before


async def test_a_files_document_node_never_shares_its_writer_id_with_the_module_entity(
    tmp_path,
) -> None:
    """Task 8 drive defect D18: the official writer keys nodes and relationship endpoints
    by writer id regardless of label. The lexical Document node and the code ``module``
    entity both used the bare file path, so in the promoted code graph every Document
    carried the module's ``contains``/FROM_CHUNK edges and 3,677 chunk FROM_DOCUMENT
    edges pointed at module entities. The Document id is namespaced and the assembled
    per-file graph refuses any collision instead of mis-wiring silently.
    """
    file_path = "pkg/mod.py"
    assert document_node_id(file_path) != module_id(file_path)
    assert document_info(file_path).uid == document_node_id(file_path)
    assert document_info(file_path).metadata == {"file_path": file_path}

    source = "class Thing:\n    def run(self) -> None:\n        return None\n"
    chunks = [
        Chunk(
            chunk_id="pkg/mod.py:1-3:0",
            content=source,
            file_path=file_path,
            start_line=1,
            end_line=3,
            token_count=12,
            embedding=[0.1, 0.2],
        )
    ]
    lexical = lexical_graph_config()
    lexical_result = await LexicalGraphBuilder(config=lexical).run(
        text_chunks=chunks_to_text_chunks(chunks), document_info=document_info(file_path)
    )
    code = extract_code_graph(
        repo_id="code",
        run_id="run-1",
        file_path=file_path,
        source=source,
        language="python",
        chunks=chunks,
        cfg=TriBridConfig(),
        root=tmp_path,
    )
    combined = assemble_code_file_graph(lexical_result.graph, code.graph)
    ids = [node.id for node in combined.nodes]
    assert len(ids) == len(set(ids))
    assert document_node_id(file_path) in ids
    assert module_id(file_path) in ids
    assert symbol_id(file_path, "Thing") in ids
    folded, report = fold_duplicate_node_ids(combined)
    assert folded == combined
    assert report == {"folded_same_label": 0}

    colliding = Neo4jGraph(
        nodes=[Neo4jNode(id=document_node_id(file_path), label="module", properties={})],
        relationships=[],
    )
    with pytest.raises(ValueError, match="shared by a Document node and a module node"):
        assemble_code_file_graph(lexical_result.graph, colliding)


def test_default_extraction_prompt_is_the_official_template_plus_naming_rules() -> None:
    """Task 8 drive finding D19 (and its cause, D24): the operator's "Semantic KG Extraction"
    prompt in System Prompts was never read by the official pipeline, which ran the library's
    default template. That template says nothing about what a ``name`` may be, so Luna named
    Epstein persons and emails with OCR noise (``-11>``, ``<=11IM11.11>``, ``777``). The LAW
    default is now the official template carrying ragweld's naming rules, and it must keep
    the three placeholders the official extractor formats.
    """
    text = TriBridConfig().system_prompts.semantic_kg_extraction
    assert "{schema}" in text and "{text}" in text and "{examples}" in text
    assert "OCR" in text and "subject line" in text
    template = extraction_prompt_template(text)
    rendered = template.format(text="Alice emailed Bob.", schema={"node_types": []}, examples="")
    assert "Alice emailed Bob." in rendered
    assert "node_types" in rendered
    # The JSON example survives str.format (doubled braces in the source).
    assert '"nodes"' in rendered and '"relationships"' in rendered


@pytest.mark.parametrize(
    ("template", "missing"),
    [
        ("Extract from: {text}", "{schema}"),
        ("Schema: {schema}", "{text}"),
        ("", "{schema}"),
        ("   ", "{schema}"),
    ],
)
def test_extraction_prompt_template_refuses_a_template_the_extractor_cannot_format(
    template: str, missing: str
) -> None:
    with pytest.raises(ValueError, match=missing.replace("{", "\\{").replace("}", "\\}")):
        extraction_prompt_template(template)


def test_semantic_extractor_carries_the_operator_template_and_structured_output() -> None:
    llm = semantic_extraction_llm(
        route_model="openai.gpt-5.6-luna",
        route_base_url="http://127.0.0.1:54000/v1",
        route_api_key="not-a-real-key",
        route_upstream="openrouter/openai/gpt-5.6-luna",
        llm_timeout_s=30,
        reasoning_effort="medium",
    )
    operator_text = "Rules: names must be readable. Types: {schema}. Examples: {examples}. Text: {text}"
    extractor = semantic_entity_relation_extractor(
        llm=llm, prompt_template=operator_text, max_concurrency=3
    )
    assert extractor.prompt_template.template == operator_text
    assert extractor.use_structured_output is True
    assert extractor.max_concurrency == 3
    assert extractor.create_lexical_graph is True


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        (
            "openrouter/google/gemini-3.5-flash-lite",
            {"temperature": 0, "extra_body": {"reasoning": {"effort": "medium"}}},
        ),
        ("openrouter/openai/gpt-5.6-luna", {"temperature": 0, "extra_body": {"reasoning": {"effort": "medium"}}}),
        ("openai/ragweld-local", {"temperature": 0, "reasoning_effort": "medium"}),
    ],
)
def test_reasoning_effort_travels_in_the_upstreams_own_protocol(upstream: str, expected: dict) -> None:
    """Follow-up finding D25: LiteLLM 1.94 only maps the OpenAI ``reasoning_effort`` parameter
    onto OpenRouter for models its own capability map knows, so every 2026 alias it does not
    know (Gemini 3.5/3.7 Flash among them) answered a semantic run with a 400
    ``UnsupportedParamsError`` and zero chunks extracted. OpenRouter's native ``reasoning``
    object passes LiteLLM untouched in ``extra_body`` and is honoured by every reasoning-capable
    model there (measured: Gemini 3.5 Flash Lite reported 112 reasoning tokens, Luna answered
    unchanged). An OpenAI-compatible upstream (the local vLLM lane) keeps the OpenAI parameter.
    """
    assert reasoning_model_params(reasoning_effort="medium", route_upstream=upstream) == expected


@pytest.mark.parametrize("upstream", ["", "   "])
def test_reasoning_effort_refuses_a_route_without_an_upstream(upstream: str) -> None:
    with pytest.raises(RuntimeError, match="upstream"):
        reasoning_model_params(reasoning_effort="medium", route_upstream=upstream)
