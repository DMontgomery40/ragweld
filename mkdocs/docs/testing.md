# Testing and Verification

<div class="grid chunk_summaries" markdown>

-   :material-test-tube:{ .lg .middle } **Zero-Mocked**

    ---

    Real integrations: no request interception or Python mocks.

-   :material-clipboard-text:{ .lg .middle } **Coverage by Change Type**

    ---

    Components → Playwright, APIs → pytest, Retrieval → relevance.

-   :material-shield-check:{ .lg .middle } **Gate to Done**

    ---

    You cannot return a response unless tests run and pass.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Real Results"
    Validate that search returns relevant chunks, not just 200 OK.

!!! note "CI Hooks"
    Stop hook blocks completion until validators and tests succeed.

!!! danger "No Mocks"
    - No Playwright `page.route(...).fulfill(...)`
    - No Python `unittest.mock` / `monkeypatch`

## Required Tests by Change Type

| Change | Required Test |
|--------|---------------|
| New component | Playwright: render, interact, verify state |
| Component edit | Playwright: existing tests still pass + new behavior |
| API endpoint | pytest: real request/response/data |
| Config field | pytest: validation works, default applies |
| Retrieval logic | pytest: search returns relevant results |
| Bug fix | Test reproduces bug, then passes after fix |

### Examples

=== "Python"
```python
# RIGHT - verify real results
import httpx

def test_search_returns_relevant_chunks():
    r = httpx.post("http://127.0.0.1:8012/api/search", json={
        "query": "authentication flow",
        "corpus_id": "my-corpus",
        "top_k": 10,
    })
    r.raise_for_status()
    results = r.json()["matches"]
    assert len(results) >= 3
    assert any("auth" in m["content"].lower() for m in results)
```

=== "curl"
```bash
curl -sS -X POST http://127.0.0.1:8012/api/search -H 'Content-Type: application/json' \
  -d '{"corpus_id":"my-corpus","query":"authentication flow","top_k":10}' | jq '[.matches[].file_path] | length'
```

=== "TypeScript"
```typescript
// Playwright example skeleton
import { test, expect } from '@playwright/test';

test('fusion weight slider updates config', async ({ page }) => {
  await page.goto('/rag');
  const slider = page.getByTestId('vector-weight-slider');
  await slider.fill('0.6');
  await page.getByTestId('save-config').click();
  await expect(page.getByTestId('config-saved-toast')).toBeVisible();
  await page.reload();
  await expect(slider).toHaveValue('0.6');
});
```

- [x] Start full stack locally (`./start.sh --with-observability`)
- [x] Configure LLM credentials in `.env`
- [ ] Convert legacy mocked tests before editing feature areas

??? info "Artifacts"
    Temporary feature tests and results go in `.tests/`; permanent tests go under `tests/`.
