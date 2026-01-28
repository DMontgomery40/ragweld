# Graph Search (Neo4j)

Neo4j enables code structure analysis through entity relationships.

## Overview

Graph search captures relationships between code entities:

- Function calls
- Class inheritance
- Module imports
- Variable references

## Configuration

```json
{
  "graph_storage": {
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "",
    "max_hops": 2,
    "include_communities": true,
    "community_algorithm": "louvain"
  }
}
```

## Entity Types

- `function` - Function definitions
- `class` - Class definitions
- `module` - Python modules
- `variable` - Important variables
- `import` - Import statements

## Relationship Types

- `calls` - Function calling another
- `imports` - Module importing
- `inherits` - Class inheritance
- `contains` - Nesting relationship
- `references` - Variable usage

## Cypher Query Example

```cypher
MATCH (f:Function)-[:calls*1..2]->(related)
WHERE f.name = 'search'
RETURN f, related
```
