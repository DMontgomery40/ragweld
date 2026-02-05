# Epstein Files Demo Implementation

## Goal
Index a 105MB raw OCR text file (~2M lines) and demonstrate TriBridRAG's tri-bridge fusion on real messy data.

---

## 1. Document-Focused Semantic KG Prompt

**File:** `server/models/tribrid_config_model.py`
**Location:** `SystemPromptsConfig`

Add a NEW field alongside the existing `semantic_kg_extraction` (keep the code prompt, add documents prompt):

```python
semantic_kg_extraction_documents: str = Field(
    default='''You are an entity extractor for OCR'd documents (scanned emails, legal filings, financial records).

Given a chunk of text (possibly with OCR errors), extract entities and relationships.

ENTITY TYPES (use as prefix):
- person: Individual names (normalize OCR typos: "Fpstein" → "epstein")  
- org: Companies, banks, foundations, agencies
- location: Cities, addresses, countries
- date: Specific dates or years mentioned
- topic: Key themes (flight, foundation, legal, financial, settlement)

RULES:
- Return ONLY valid JSON (no markdown, no explanation)
- Normalize obvious OCR errors using context
- Keep names lowercase, underscored: "jeffrey_epstein" not "Jeffrey Epstein"
- Extract sender/recipients if text looks like an email
- Max 10 concepts, max 8 relations
- Skip noise words, page numbers, headers

JSON FORMAT:
{
  "concepts": ["person:jeffrey_epstein", "org:jp_morgan", "location:palm_beach", "date:2008"],
  "relations": [
    {"source": "person:jeffrey_epstein", "target": "org:jp_morgan", "relation_type": "references"}
  ]
}

Allowed relation_type: related_to, references''',
    description="Prompt for LLM-assisted semantic KG extraction from documents"
)
```

---

## 1b. Expose New Prompt in UI

**File:** `server/api/prompts.py`
**Location:** `_build_prompts_payload()`

Add the new prompt to the prompts editor:

```python
add_system_prompt("semantic_kg_extraction_documents", category="indexing", label="Semantic KG Extraction (Documents)")
```

This surfaces it in Eval → System Prompts alongside the existing code-focused prompt.

---

## 2. Add Corpus-Type Config Option

**File:** `server/models/tribrid_config_model.py`
**Location:** `GraphIndexingConfig`

Add field to select prompt style:

```python
semantic_kg_corpus_type: Literal["code", "documents"] = Field(
    default="code",
    description="Corpus type hint for semantic KG extraction. 'documents' uses entity-focused extraction (people, orgs, locations)."
)
```

**File:** `server/api/index.py`
**Location:** `_run_index()` where `llm_prompt` is resolved

Logic:
```python
if cfg.graph_indexing.semantic_kg_corpus_type == "documents":
    llm_prompt = str(cfg.system_prompts.semantic_kg_extraction_documents or "").strip()
else:
    llm_prompt = str(cfg.system_prompts.semantic_kg_extraction or "").strip()
```

**Alternative:** Just add a second prompt field `semantic_kg_extraction_documents` and let user pick via UI.

---

## 3. Frontend: Corpus Type Selector

**File:** `web/src/components/indexing/IndexingConfig.tsx` (or wherever graph indexing config lives)

Add dropdown when `semantic_kg_enabled` is true:

```tsx
{config.graph_indexing.semantic_kg_enabled && (
  <Select
    label="Corpus Type"
    value={config.graph_indexing.semantic_kg_corpus_type}
    onChange={(v) => updateConfig('graph_indexing.semantic_kg_corpus_type', v)}
    options={[
      { value: 'code', label: 'Code Repository' },
      { value: 'documents', label: 'Documents (emails, legal, OCR)' },
    ]}
    tooltip="semantic_kg_corpus_type"
  />
)}
```

---

## 4. Chunking Config for Large Documents

For a single 105MB file, default chunk settings work but consider:

```python
# Larger chunks for documents (more context for LLM extraction)
chunking:
  chunk_size: 2000      # vs 1000 default
  chunk_overlap: 300    # vs 200 default
```

**No code change needed** - just config. User can adjust in UI.

---

## 5. Glossary Entries

**File:** `data/glossary.json`

Add:
```json
{
  "term": "semantic_kg_corpus_type",
  "definition": "Hint for semantic knowledge graph extraction. 'code' extracts functions, classes, modules. 'documents' extracts people, organizations, locations, dates from OCR'd text.",
  "category": "graph"
},
{
  "term": "semantic_kg_extraction_documents", 
  "definition": "System prompt for extracting entities from document corpora (emails, legal filings, scanned PDFs). Handles OCR errors and extracts person/org/location entities.",
  "category": "prompts"
}
```

---

## 6. Implementation Order

1. **Add `semantic_kg_extraction_documents` prompt** to `SystemPromptsConfig` (THE LAW)
2. **Add `semantic_kg_corpus_type` field** to `GraphIndexingConfig` (THE LAW)
3. **Run `uv run scripts/generate_types.py`** to regenerate TypeScript
4. **Update `server/api/index.py`** to select prompt based on corpus type
5. **Add glossary entries**
6. **Add frontend dropdown** in graph indexing config
7. **Test on small sample** (first 1000 lines of the file)
8. **Full index** with LLM semantic KG

---

## 7. Test Commands

```bash
# Create corpus
curl -X POST http://localhost:8123/api/corpora -H "Content-Type: application/json" \
  -d '{"repo_id": "epstein_files", "name": "Epstein Files", "path": "/Users/davidmontgomery/epstein-files"}'

# Update config for documents
curl -X PUT http://localhost:8123/api/config?corpus_id=epstein_files -H "Content-Type: application/json" \
  -d '{
    "graph_indexing": {
      "semantic_kg_enabled": true,
      "semantic_kg_mode": "llm",
      "semantic_kg_corpus_type": "documents",
      "semantic_kg_max_chunks": 50000
    },
    "chunking": {
      "chunk_size": 2000,
      "chunk_overlap": 300
    }
  }'

# Start indexing
curl -X POST http://localhost:8123/api/index/start -H "Content-Type: application/json" \
  -d '{"repo_id": "epstein_files", "repo_path": "/Users/davidmontgomery/epstein-files", "force_reindex": true}'
```

---

## 8. Demo Queries

```
"Who is connected to JP Morgan?"
"What happened in 2008?"
"Find emails about flights"
"What organizations are mentioned?"
"Who communicated with Michael Wolff?"
```

---

## 9. Success Criteria

- [ ] Index completes without crashing
- [ ] Neo4j has person:/org:/location: entities (not just code concepts)
- [ ] Graph search returns chunks for entity queries
- [ ] Fusion improves recall over single-leg search
- [ ] OCR typos don't completely break entity extraction
