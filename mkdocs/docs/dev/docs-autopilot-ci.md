# Docs Autopilot (CI soft-fail updates)

<div class="grid chunk_summaries" markdown>

-   :material-cog:{ .lg .middle } **Soft-fail patch apply**

    ---

    The CI no longer hard-fails when the LLM-generated patch can’t apply. We continue the job, record the error, and surface clear warnings.

-   :material-file:{ .lg .middle } **Marker file = source of truth**

    ---

    When `git apply` fails, the workflow writes `mkdocs-docs-llm.apply-failed.txt` with the error. Downstream steps read this file.

-   :material-alert:{ .lg .middle } **Action warnings, not silent drops**

    ---

    The generator emits `::warning::docs-autopilot: ...` so you can see what went wrong directly in GitHub Actions logs.

-   :material-console:{ .lg .middle } **Repro locally with one flag**

    ---

    Use `--soft-fail-apply-errors` in `generate_docs_from_diff.py` to mirror CI behavior on your machine.

</div>

[Docs Autopilot](docs-autopilot.md){ .md-button .md-button--primary }
[Workflow](docs-autopilot-workflow.md){ .md-button }
[Dev workflow](../dev_workflow.md){ .md-button }

!!! note "Scope"
    This page documents the CI-facing changes to ragweld’s Docs Autopilot introduced alongside updates to:
    
    - `.github/workflows/docs-automation.yml`
    - `scripts/docs_ai/generate_docs_from_diff.py`

## What changed (and why)

- The workflow now calls the generator with a new flag: `--soft-fail-apply-errors`.
- If the LLM produces a patch that cannot be cleanly applied, the run does not fail the job immediately.
- Instead, the script writes `mkdocs-docs-llm.apply-failed.txt` containing the apply error, and emits GitHub Actions warnings.
- A lightweight “Docs autopilot failed” step adds summary context if the marker file exists.
- We still upload both the patch and the apply-failed marker as artifacts for inspection.

Rationale:

- Docs edits often race with concurrent human commits. Hard-failing CI on a non-applicable patch wastes time.
- We want visibility without blocking: the docs still build later in the job so you get a trustworthy mkdocs signal.

## Updated GitHub Actions workflow snippets

=== "Generate docs patch (apply)"

    ```yaml
    - name: Generate docs patch (apply)
      run: |
        BASE="${{ github.event.inputs.base_ref }}"
        if [ -z "$BASE" ]; then
          # Fallback to current branch if no manual input provided
          BASE="origin/${{ github.ref_name }}"
        fi
        echo "Using base ref: $BASE"
        python scripts/docs_ai/generate_docs_from_diff.py --base "$BASE" --llm openai --apply --soft-fail-apply-errors  # (1)!
    ```

    1. New behavior: on apply failure, write `mkdocs-docs-llm.apply-failed.txt`, emit `::warning::`, and continue the job.

=== "Failure summary + artifact upload"

    ```yaml
    - name: Docs autopilot failed
      if: hashFiles('mkdocs-docs-llm.apply-failed.txt') != ''  # (2)!
      run: |
        echo "## Docs Autopilot Failed" >> $GITHUB_STEP_SUMMARY
        echo "" >> $GITHUB_STEP_SUMMARY
        echo "The LLM patch was generated but could not be applied cleanly." >> $GITHUB_STEP_SUMMARY
        echo "See mkdocs-docs-llm.apply-failed.txt for details. Artifacts were uploaded." >> $GITHUB_STEP_SUMMARY

    - name: Upload docs autopilot artifacts
      uses: actions/upload-artifact@v4
      with:
        name: mkdocs-docs-llm-patch
        path: |
          mkdocs-docs-llm.patch
          mkdocs-docs-llm.apply-failed.txt  # (3)!
        if-no-files-found: ignore
    ```

    2. Deterministic, file-based signal: only runs when the marker exists.
    3. Upload the failure marker alongside the patch so you can triage locally.

## Local reproduction (match CI behavior)

Use the same soft-fail switch locally:

```bash
python scripts/docs_ai/generate_docs_from_diff.py \
  --base origin/main \
  --llm openai \
  --apply \
  --soft-fail-apply-errors  # (1)!
```

1. Mirrors CI: if the patch can’t be applied, the script writes `mkdocs-docs-llm.apply-failed.txt`, prints `::warning::` logs, and exits successfully.

??? tip "Working with an existing patch file"
    If you already have a patch (from artifacts or a previous run), apply it directly:

    ```bash
    python scripts/docs_ai/generate_docs_from_diff.py --apply-patch mkdocs-docs-llm.patch
    ```

## Semantics and signals

mkdocs-docs-llm.patch
: The unified diff produced by the LLM. Suitable for `git apply --index`.

mkdocs-docs-llm.apply-failed.txt
: Written only when a patch apply error occurs. Contains the raw `git apply` error message and a trailing newline. Presence of this file drives the CI “failed” summary and artifact upload. Safe to delete.

::warning::docs-autopilot
: Log prefix used by the generator for GitHub Actions warnings. Helpful for quickly grepping pipeline issues.

!!! tip "Where warnings come from"
    The generator now uses a `_gh_warning()` helper to emit GitHub Actions warnings. You’ll see these in the job logs even when the job continues.

## CI flow (at a glance)

```mermaid
flowchart LR
  A["Git diff\\n(base..HEAD)"] --> B["Plan + prompt\\n(docs_prompt_base.md)"]
  B --> C["LLM patch\\n(mkdocs-docs-llm.patch)"]
  C --> D["git apply"]
  D --> E{"Apply ok?"}
  E -- "yes" --> F["Build docs\\nmkdocs build --strict"]
  E -- "no" --> G["Write marker\\nmkdocs-docs-llm.apply-failed.txt"]
  G --> H["Warn in CI\\n::warning::docs-autopilot"]
  H --> F
```

## Operator checklist (triage quickly)

- [ ] Open GitHub Actions logs and search for `::warning::docs-autopilot`.
- [ ] Download artifacts: `mkdocs-docs-llm.patch` and `mkdocs-docs-llm.apply-failed.txt`.
- [ ] Inspect the marker file to understand the apply error.
- [ ] Try applying the patch locally on a clean branch.
- [ ] If conflicts are due to recent doc edits, manually port the safe hunks and re-run CI.
- [ ] Always run `mkdocs build --strict` locally after resolving conflicts.

??? info "Why does a patch fail to apply?"
    Common causes:

    - Concurrent edits to the same docs section changed context lines.
    - Files were moved/renamed after the LLM produced its patch.
    - The patch targets a page that was deleted or replaced in the meantime.
    - Whitespace/context drift in long code blocks changed anchors the patch relies on.

    Practical fixes:

    - Re-run the generator against the latest base (reduces drift).
    - Apply the patch manually and resolve conflicts with your editor.
    - If the LLM added a new page, create it manually and port the content.

## Safety and failure modes

!!! warning "Soft-fail does not mean success"
    Soft-fail prevents premature CI failures when applying patches, but your docs still need to build. The dedicated “Build documentation” step continues to enforce `mkdocs build --strict`.

!!! note "Idempotency"
    The generator clears any stale `mkdocs-docs-llm.apply-failed.txt` before running. If you see the file at the end of a run, it reflects the most recent apply attempt.

## Reference snippets (copy/paste)

=== "Minimal CI call"

```yaml
- name: Generate docs patch (apply)
  run: |
    python scripts/docs_ai/generate_docs_from_diff.py --base "origin/${{ github.ref_name }}" --llm openai --apply --soft-fail-apply-errors
```

=== "Detect failure via marker"

```yaml
if: hashFiles('mkdocs-docs-llm.apply-failed.txt') != ''
```

=== "Upload artifacts"

```yaml
with:
  name: mkdocs-docs-llm-patch
  path: |
