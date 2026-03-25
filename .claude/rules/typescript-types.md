---
paths:
  - "web/src/**/*.{ts,tsx}"
---

# TypeScript Type Rules (Frontend)

> Branch canon for `feat/oss-composition-kickoff`: no frontend adapters, fallback rendering for removed contracts, or dual old/new payload support.

## Rule 2: No Hand-Written API Types
All TypeScript interfaces for API data MUST come from `generated.ts`.

```typescript
// WRONG - hand-written interface
interface SearchResponse {
  results: ChunkMatch[];
  latency: number;
}

// RIGHT - imported from generated
import { SearchResponse } from '../types/generated';
```

## No Adapters/Transformers/Mappers
- **WRONG:** Write an adapter function to convert API shape -> component shape
- **RIGHT:** Change the Pydantic model to return the right shape

## Architecture Smells (BANNED in .tsx files)
- `interface` declarations that don't trace back to Pydantic -> import from `generated.ts`
- `class *Adapter` / `class *Transformer` / `class *Mapper` -> fix the Pydantic model
- `function transform*` -> fix the Pydantic model

## Field Constraints
Pydantic `Field()` constraints define valid ranges. The UI MUST honor them:
- `ge`/`le` -> slider min/max
- `default` -> slider default
- Don't override these in the frontend. The Pydantic model IS the spec.
