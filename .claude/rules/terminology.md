# Terminology & Naming Conventions

> Local `main` is canonical: do not preserve legacy naming or copy in operator-facing surfaces after a subsystem has been replaced.

## Naming (ragweld vs tribrid)
- Repo = `ragweld`, internal identifiers = `tribrid`. This is expected.
- Do NOT attempt mass-renames of `tribrid` -> `ragweld`.

## Corpus vs Repo
- TriBridRAG is **corpus-first**: a corpus is any folder you index/search/GraphRAG over
- Code uses `repo_id` for the corpus identifier. Treat `repo_id` as `corpus_id`.

## Terms That Don't Exist

| WRONG | RIGHT |
|-------|-------|
| card, cards | chunk_summary, chunk_summaries |
| golden questions | eval_dataset |
| ranker | reranker |
| profile, profiles | (removed - no profiles) |
