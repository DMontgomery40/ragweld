---
paths:
  - "server/**/*.py"
---

# Schema Boundary Rules (Python/Server)

> Local `main` is canonical. Modernization is replacement-only: no legacy
> fallbacks, compatibility shims, transition-period dual paths, or silent
> routing back into a superseded subsystem.

## Validated serialized boundaries

Use Pydantic for FastAPI request/response bodies, persisted operator
configuration, and untrusted external, artifact, or cross-process payloads.
Boundary schemas belong in the closest domain-owned module and may be
registered through the current aggregate for TypeScript generation.

Internal computation records do not need to become public schemas. Dataclasses,
`TypedDict`, `Protocol`, enums, and plain classes are all valid internal types.

## Explicit transformations are allowed

Named, typed, one-directional, contract-tested transformations are appropriate
at real semantic boundaries, including provider-to-domain, persistence-to-domain,
API-to-domain, and API-wire-to-UI-view-model boundaries.

Hidden or lossy transforms, payload shape guessing, competing canonical
schemas, compatibility translators, and dual-read/write paths remain forbidden.

## Configuration is for real tunables

Operator/runtime choices belong in typed, domain-owned config composed by
`TriBridConfig`. Secrets and deployment wiring remain environment/infrastructure
inputs. Constants, protocol invariants, derived values, and internal structure
stay ordinary code rather than fake configuration knobs.

## Boundary constraints

Pydantic `Field()` constraints on public/configuration boundaries are contract:
the UI and API must honor ranges, defaults, and validation behavior.

## Banned Python Imports
```python
# BANNED - we don't use these
from redis import ...            # Removed
import redis                     # Removed
from langchain import ...        # Banned (use langgraph directly)
import langchain                 # Banned (use langgraph directly)
```
LangGraph is allowed directly. Qdrant, Haystack, and Docling are part of the
locked target stack.
