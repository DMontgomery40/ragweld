from importlib.metadata import version
from inspect import iscoroutinefunction, signature

from neo4j_graphrag.components.kg_writer import Neo4jWriter
from neo4j_graphrag.components.resolver import SinglePropertyExactMatchResolver
from neo4j_graphrag.components.schema import GraphSchema, SchemaFromTextExtractor
from neo4j_graphrag.components.types import LexicalGraphConfig
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever
from packaging.version import Version


def test_pinned_graphrag_contract_matches_the_replacement_design() -> None:
    assert version("neo4j-graphrag") == "1.19.0"
    neo4j_driver = Version(version("neo4j"))
    assert neo4j_driver.major == 5
    assert neo4j_driver >= Version("5.28.4")
    lexical = LexicalGraphConfig()
    assert lexical.chunk_to_document_relationship_type == "FROM_DOCUMENT"
    assert lexical.next_chunk_relationship_type == "NEXT_CHUNK"
    assert lexical.node_to_chunk_relationship_type == "FROM_CHUNK"
    assert "filter_query" in signature(SinglePropertyExactMatchResolver).parameters
    qdrant = signature(QdrantNeo4jRetriever).parameters
    assert {
        "collection_name",
        "id_property_external",
        "id_property_neo4j",
        "retrieval_query",
        "id_property_getter",
    } <= set(qdrant)
    assert hasattr(GraphSchema, "save") and hasattr(GraphSchema, "from_file")
    assert "use_structured_output" in signature(SchemaFromTextExtractor).parameters
    assert list(signature(Neo4jWriter.run).parameters)[:3] == [
        "self",
        "graph",
        "lexical_graph_config",
    ]
    assert iscoroutinefunction(
        Neo4jWriter.run
    ), "1.19 Neo4jWriter.run is async despite using a sync driver"
