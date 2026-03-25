---
paths:
  - "tests/**/*"
  - ".tests/**/*"
  - "web/tests/**/*"
---

# Testing Rules

> Branch canon for `feat/oss-composition-kickoff`: tests must validate the replacement path. Do not add tests that bless legacy fallbacks, compatibility shims, or transition-period behavior.

## Mandatory Testing
Every change MUST be tested before completion.
- Temporary feature tests -> `.tests/` (gitignored)
- Reusable permanent tests -> `tests/` (not gitignored)

## Zero-Mocked Tests (enforced for new/edited tests)

**No Playwright API mocking:**
- Do NOT use `page.route(...)` + `route.fulfill(...)` to fake backend responses

**No Python mocking:**
- Do NOT use `monkeypatch`, `unittest.mock`, `MagicMock`, `patch()`

**No skip stubs:**
- Tests must fail loudly if code raises `NotImplementedError`

**Migration rule:** If you touch a feature area with an existing mocked test, convert it to a real test first.

## How to Run Real E2E
```bash
./start.sh --with-observability   # Full stack with DBs + Loki
# Ensure LLM credentials in .env
```

## GUI Changes -> Playwright Tests
Real interaction tests, not "screen isn't black":
```typescript
// WRONG
test('page loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).not.toBeEmpty();
});

// RIGHT
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

## API/Search Changes -> Real Results
```python
# WRONG
def test_search():
    response = client.post("/search", json={"query": "test"})
    assert response.status_code == 200

# RIGHT
def test_search_returns_relevant_chunks():
    response = client.post("/api/search", json={
        "query": "authentication flow",
        "repo_id": "my-corpus"
    })
    results = response.json()["matches"]
    assert len(results) >= 3
    assert any("auth" in r["content"].lower() for r in results)
```

## What "Tested" Means

| Change Type | Required Test |
|-------------|---------------|
| New component | Playwright: render, interact, verify state |
| Component edit | Playwright: existing tests pass + new behavior |
| API endpoint | pytest: real request, real response, real data |
| Config field | pytest: validation works, default applies |
| Retrieval logic | pytest: search returns relevant results |
| Bug fix | Test that reproduces the bug, then passes after fix |

## No Exceptions
- "It's a small change" -> Still test it
- "I'm confident it works" -> Prove it
- "Tests are slow" -> Run them anyway
- "It's just CSS" -> Playwright screenshot comparison
