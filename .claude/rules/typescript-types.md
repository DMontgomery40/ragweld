---
paths:
  - "web/src/**/*.{ts,tsx}"
---

# TypeScript Boundary Type Rules (Frontend)

> Local `main` is canonical. Do not preserve removed contracts with fallback
> rendering, dual payload support, or silent shape guessing.

## Generated public wire contracts

FastAPI request/response and public configuration payloads come from
`web/src/types/generated.ts`. Do not hand-copy those payloads into API or
service modules under new names.

```typescript
import type { SearchResponse } from '../types/generated';
```

## Local UI types are local

Component props, form state, Zustand state, browser-only state, and derived view
models may be handwritten near their owning feature. They must describe UI
semantics rather than duplicate a backend wire payload.

## Explicit view-model transformations are allowed

An explicit, typed, tested transformation from a generated wire contract to a
local UI view model is legitimate. Keep it one-directional and feature-owned.
Do not build mapper chains, hide field loss, guess between old/new shapes, or
maintain competing canonical transport schemas.

## Boundary constraints

Pydantic `Field()` constraints on public/configuration boundaries define valid ranges. The UI must honor them:
- `ge`/`le` -> slider min/max
- `default` -> slider default
- Do not override these with incompatible frontend limits.
