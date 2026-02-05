from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from server.models.tribrid_config_model import (
    CorpusScope,
    PromptCategory,
    PromptMetadata,
    PromptUpdateRequest,
    PromptUpdateResponse,
    PromptsResponse,
    SystemPromptsConfig,
    TriBridConfig,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.config_store import save_config as save_scoped_config

router = APIRouter(tags=["prompts"])


def _title(s: str) -> str:
    return " ".join([p.capitalize() for p in s.replace("_", " ").split()])


def _build_prompts_payload(cfg: TriBridConfig) -> PromptsResponse:
    """Expose system prompts for the UI editor.

    Keys are stable strings used by the frontend:
    - system prompts: fields from SystemPromptsConfig (e.g. "query_expansion")
    - chat prompts: "chat.<field>" for ChatConfig system_prompt_* fields
    """

    prompts: dict[str, str] = {}
    meta: dict[str, PromptMetadata] = {}

    sp = cfg.system_prompts
    sp_fields = SystemPromptsConfig.model_fields

    def category_for_system_prompt(key: str) -> PromptCategory:
        # Heuristic defaults so new prompts auto-appear without editing this file.
        if key == "main_rag_chat":
            return "chat"
        if key.startswith("query_"):
            return "retrieval"
        if key.startswith("eval_"):
            return "evaluation"
        return "indexing"

    label_overrides: dict[str, str] = {
        "main_rag_chat": "Main RAG Chat",
        "query_expansion": "Query Expansion",
        "query_rewrite": "Query Rewrite",
        "eval_analysis": "Eval Analysis",
        "semantic_chunk_summaries": "Semantic Chunk Summaries",
        "lightweight_chunk_summaries": "Lightweight Chunk Summaries",
        "code_enrichment": "Code Enrichment",
        "semantic_kg_extraction": "Semantic KG Extraction",
    }

    # ALL SystemPromptsConfig fields (Pydantic is the source of truth).
    for key, field_info in sp_fields.items():
        prompts[key] = str(getattr(sp, key) or "")
        meta[key] = PromptMetadata(
            label=label_overrides.get(key) or _title(key),
            description=str(field_info.description or ""),
            category=category_for_system_prompt(key),
        )

    # Chat-level prompts (read-only here; edited in Chat Settings)
    chat = cfg.chat
    chat_prompts: list[tuple[str, str]] = [
        ("system_prompt_base", "Base prompt (legacy)"),
        ("system_prompt_rag_suffix", "RAG suffix (legacy)"),
        ("system_prompt_recall_suffix", "Recall suffix (legacy)"),
        ("system_prompt_direct", "Direct (no context)"),
        ("system_prompt_rag", "RAG only"),
        ("system_prompt_recall", "Recall only"),
        ("system_prompt_rag_and_recall", "RAG + Recall"),
    ]
    for field, label in chat_prompts:
        key = f"chat.{field}"
        prompts[key] = str(getattr(chat, field, "") or "")
        desc = str(getattr(chat.model_fields.get(field), "description", "") or "").strip()
        if not desc:
            desc = f"Chat prompt: {field}"
        meta[key] = PromptMetadata(
            label=label,
            description=desc,
            category="chat",
            editable=False,
            link_route=f"/chat?subtab=settings&prompt={field}",
            link_label="Open Chat Settings",
        )

    return PromptsResponse(prompts=prompts, metadata=meta)


def _set_prompt_value(cfg: TriBridConfig, prompt_key: str, value: str) -> TriBridConfig:
    """Mutate cfg in-place for a supported prompt key."""
    if prompt_key.startswith("chat."):
        field = prompt_key.split(".", 1)[1].strip()
        if field not in cfg.chat.model_fields:
            raise KeyError(prompt_key)
        setattr(cfg.chat, field, value)
        return cfg

    if prompt_key in cfg.system_prompts.model_fields:
        setattr(cfg.system_prompts, prompt_key, value)
        return cfg

    raise KeyError(prompt_key)


def _default_value_for(prompt_key: str) -> str:
    """Return the LAW default for a prompt key."""
    default_cfg = TriBridConfig()
    if prompt_key.startswith("chat."):
        field = prompt_key.split(".", 1)[1].strip()
        return str(getattr(default_cfg.chat, field, "") or "")
    return str(getattr(default_cfg.system_prompts, prompt_key, "") or "")


@router.get("/prompts", response_model=PromptsResponse)
async def list_prompts(scope: CorpusScope = Depends()) -> PromptsResponse:
    try:
        cfg = await load_scoped_config(repo_id=scope.resolved_repo_id)
        return _build_prompts_payload(cfg)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/prompts/{prompt_key}", response_model=PromptUpdateResponse)
async def update_prompt(
    prompt_key: str,
    body: PromptUpdateRequest,
    scope: CorpusScope = Depends(),
) -> PromptUpdateResponse:
    key = (prompt_key or "").strip()
    if key.startswith("chat."):
        raise HTTPException(
            status_code=403,
            detail="Chat prompts are read-only in Eval → System Prompts. Edit them in Chat → Settings.",
        )
    if not (body.value or "").strip():
        raise HTTPException(status_code=400, detail="Prompt value cannot be empty")
    try:
        cfg = await load_scoped_config(repo_id=scope.resolved_repo_id)
        _set_prompt_value(cfg, key, body.value)
        await save_scoped_config(cfg, repo_id=scope.resolved_repo_id)
        return PromptUpdateResponse(ok=True, prompt_key=key, message="Prompt updated")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/prompts/reset/{prompt_key}", response_model=PromptUpdateResponse)
async def reset_prompt(
    prompt_key: str,
    scope: CorpusScope = Depends(),
) -> PromptUpdateResponse:
    key = (prompt_key or "").strip()
    if key.startswith("chat."):
        raise HTTPException(
            status_code=403,
            detail="Chat prompts are read-only in Eval → System Prompts. Edit them in Chat → Settings.",
        )
    try:
        cfg = await load_scoped_config(repo_id=scope.resolved_repo_id)
        _set_prompt_value(cfg, key, _default_value_for(key))
        await save_scoped_config(cfg, repo_id=scope.resolved_repo_id)
        return PromptUpdateResponse(ok=True, prompt_key=key, message="Prompt reset")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
