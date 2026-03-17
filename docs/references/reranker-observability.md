# Reranker Observability

Source of truth:

- `/Users/davidmontgomery/ragweld/server/api/reranker.py`
- `/Users/davidmontgomery/ragweld/server/retrieval/rerank.py`
- `/Users/davidmontgomery/ragweld/server/observability/metrics.py`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/reranker-training.json`
- `/Users/davidmontgomery/ragweld/web/src/components/RerankerTraining/TrainingStudio.tsx`

What exists now:

- Prometheus metrics cover reranker training lifecycle, stage latencies, evaluation, triplet materialization quality, promotion attempts, and diagnostic event volumes.
- Run-specific structured diagnostics live beside each reranker training run under `data/reranker_train_runs/<run_id>/diagnostics.jsonl`.
- The training studio can fetch and download per-run diagnostics, and training events now carry `operator_hint` for failure/debug paths.
- Grafana has a provisioned `reranker-training` dashboard preset for training/eval/promotion/inference telemetry.

Design rule:

- Keep labels low-cardinality. No corpus ids, file paths, model ids, or query text in Prometheus labels.
- Put high-detail debugging context in structured diagnostics records and operator hints, not metric labels.
- Training telemetry should separate:
  - triplet/log quality issues
  - backend/runtime prerequisites
  - train-loop stability
  - evaluation quality
  - promotion outcomes
  - live inference symptoms
