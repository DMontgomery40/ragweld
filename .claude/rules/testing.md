---
paths:
  - "tests/**/*"
  - ".tests/**/*"
  - "web/tests/**/*"
---

# Testing Rules

> Local `main` is canonical: tests must validate the replacement path. Do not add tests that bless legacy fallbacks, compatibility shims, or transition-period behavior.

## Mandatory Testing
Every change MUST be tested before completion.
- Temporary feature tests -> `.tests/` (gitignored)
- Reusable permanent tests -> `tests/` (not gitignored)

## Real Queries Only — NEVER "test" / "hello" (hard rule, 2026-08-22)

Every retrieval, chat, eval, search, or answer exercise — in tests, manual
probes, browser drives, and scripts — MUST use a **real domain question** about
the indexed corpus. Placeholder inputs are banned outright:

- BANNED as a query/message anywhere: `test`, `testing`, `hello`, `hi`, `foo`,
  `ping`, `asdf`, lorem ipsum, or any content-free string.
- REQUIRED: a genuine question a user of that corpus would ask (e.g. for the
  Epstein corpus: "Which flights did Jeffrey Epstein arrange for Barry Cohen in
  October 2017?"; for the acceptance corpus: a real sensor-calibration question).

Why this is a hard rule: every real query/answer pair is a **triplet-mining
signal for the reranker**. Placeholder queries poison the reranker training
data and prove nothing about retrieval quality. A green test built on "test" or
"hello" is a fake-green test and will be rejected in review.

## Adversarial Review for Major Features (hard rule, 2026-08-22)

Any **major feature or material slice** (new subsystem, new lane, a cutover, a
new external integration, anything that changes a public boundary or the
runtime topology) MUST be adversarially reviewed by an independent stronger
model BEFORE it is considered done — not only self-verified.

- Preferred: `codex exec` with **high reasoning effort**, pointed at the diff,
  prompted to REFUTE the change (find correctness bugs, fake-green tests,
  contract drift, hidden fallbacks, blocking-IO, race conditions).
- Record the review outcome and any fixes in the slice's exec-plan/memory note.
- Trivial mechanical edits (copy, formatting, a one-line fix with a test) do not
  require this; use judgment, and when unsure, review.

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
