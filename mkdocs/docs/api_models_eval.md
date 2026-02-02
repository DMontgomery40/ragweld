# Evaluation Models

<div class="grid chunk_summaries" markdown>

-   :material-clipboard-text-search:{ .lg .middle } **Eval Dataset**

    ---

    `EvalDatasetItem` defines questions and expected paths.

-   :material-chart-line:{ .lg .middle } **Metrics**

    ---

    `EvalMetrics`, `EvalRun`, `EvalResult` capture performance.

-   :material-compare:{ .lg .middle } **Comparisons**

    ---

    `EvalComparisonResult` compares two runs.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

| Model | Purpose |
|-------|---------|
| `EvalDatasetItem` | Single question + expected file paths |
| `EvalMetrics` | Aggregated metrics (MRR, Recall@K, NDCG@10, latency percentiles) |
| `EvalRun` | Complete run with config snapshot and results |
| `EvalComparisonResult` | Delta between baseline and current runs |

```mermaid
flowchart TB
    Dataset["Eval Dataset"] --> Run["Eval Run"]
    Run --> Metrics["Eval Metrics"]
    Run --> Results["Per-Entry Results"]
    Metrics --> Compare["Compare Runs"]
```

=== "Python"
```python
import httpx
base = "http://localhost:8000"
print(httpx.post(f"{base}/reranker/evaluate", json={"corpus_id": "tribrid"}).json())
```

=== "curl"
```bash
BASE=http://localhost:8000
curl -sS -X POST "$BASE/reranker/evaluate" -H 'Content-Type: application/json' -d '{"corpus_id":"tribrid"}' | jq .
```

=== "TypeScript"
```typescript
const report = await (await fetch('/reranker/evaluate', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id: 'tribrid' }) })).json();
```
