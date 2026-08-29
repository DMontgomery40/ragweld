# Architecture reference (generated)

These pages are regenerated from the code, compose files and configuration model on every
docs-autopilot run. They are the authoritative diagrams; narrative pages link here rather than
redrawing the system by hand.

- [Runtime topology](runtime-topology.md) - every service, dependency and port across the base,
  observability and pve1 compose files
- [API surface](api-surface.md) - every route, grouped by router, with handler and response model
- [Retrieval pipeline](retrieval-pipeline.md) - the three legs, fusion, boosts, reranking, gating and
  generation with the real configuration keys and defaults
- [Configuration model](config-model.md) - the `TriBridConfig` composition root
