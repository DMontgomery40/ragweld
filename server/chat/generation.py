from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Callable

import httpx

from server.chat.provider_router import ProviderRoute
from server.models.chat_config import ImageAttachment, OpenRouterConfig
from server.models.retrieval import ChunkMatch


def _format_chunks_for_context(chunks: list[ChunkMatch]) -> str:
    if not chunks:
        return "No relevant context found."
    parts: list[str] = []
    for ch in chunks:
        header = f"## {ch.file_path}:{int(ch.start_line)}-{int(ch.end_line)}"
        if ch.language:
            header += f" ({ch.language})"
        parts.append(f"{header}\n```\n{ch.content}\n```")
    return "\n\n".join(parts)


def _attachment_to_openai_part(att: ImageAttachment) -> dict[str, Any]:
    if att.url:
        url = str(att.url)
    else:
        # Spec: base64 is provided without a `data:` prefix.
        url = f"data:{att.mime_type};base64,{att.base64}"
    return {"type": "image_url", "image_url": {"url": url}}


def _build_messages(*, system_prompt: str, user_message: str, images: list[ImageAttachment]) -> list[dict[str, Any]]:
    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        content.extend([_attachment_to_openai_part(att) for att in images])
        user_payload: dict[str, Any] = {"role": "user", "content": content}
    else:
        user_payload = {"role": "user", "content": user_message}
    return [{"role": "system", "content": system_prompt}, user_payload]


def _openrouter_headers(*, api_key: str, cfg: OpenRouterConfig) -> dict[str, str]:
    # OpenRouter recommends providing app identity headers.
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    site_name = (cfg.site_name or "").strip()
    if site_name:
        headers["X-Title"] = site_name
    return headers


def _bearer_headers(*, api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

def _summarize_provider_error(resp: httpx.Response) -> str:
    """Best-effort extraction of provider error details (safe for UI/debug logs)."""
    try:
        raw = resp.text or ""
    except Exception:
        raw = ""

    if not raw:
        return ""

    # Prefer structured JSON error messages when available.
    try:
        data: Any = resp.json()
        # OpenAI-style: {"error": {"message": "...", ...}}
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
                # Some providers use {"error":{"type":"...","code":"...","param":"..."}}
                return json.dumps(err, ensure_ascii=False)[:400]
            # OpenRouter sometimes: {"message":"..."} or {"error":"..."}
            msg = data.get("message") or data.get("error")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    except Exception:
        pass

    # Fallback to raw body snippet (keep bounded).
    return raw.strip()[:400]


async def generate_chat_text(
    *,
    route: ProviderRoute,
    openrouter_cfg: OpenRouterConfig,
    system_prompt: str,
    user_message: str,
    images: list[ImageAttachment],
    temperature: float,
    max_tokens: int,
    context_text: str | None = None,
    context_chunks: list[ChunkMatch],
    timeout_s: float = 120.0,
) -> tuple[str, str | None]:
    """Generate a single non-streaming chat response (OpenAI-compatible)."""

    if context_text is not None:
        context_block = str(context_text or "").strip()
    else:
        context_block = _format_chunks_for_context(context_chunks)

    prompt = system_prompt if not context_block else f"{system_prompt}\n\n## Context\n{context_block}"
    messages = _build_messages(system_prompt=prompt, user_message=user_message, images=images)

    base_url = route.base_url.rstrip("/")
    url = (
        f"{base_url}/chat/completions"
        if route.kind in {"openrouter", "cloud_direct"}
        else f"{base_url}/v1/chat/completions"
    )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if route.kind == "openrouter":
        if not route.api_key:
            raise RuntimeError("OpenRouter enabled but OPENROUTER_API_KEY is not set")
        headers = _openrouter_headers(api_key=route.api_key, cfg=openrouter_cfg)
    if route.kind == "cloud_direct":
        if not route.api_key:
            raise RuntimeError("Cloud provider enabled but API key is not set")
        headers = _bearer_headers(api_key=route.api_key)

    payload: dict[str, Any] = {
        "model": route.model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
        except httpx.HTTPStatusError as e:
            status = int(getattr(e.response, "status_code", 0) or 0)
            detail = ""
            try:
                msg = _summarize_provider_error(e.response)
                if msg:
                    detail = f": {msg}"
            except Exception:
                detail = ""
            if status == 401:
                if route.kind == "openrouter":
                    raise RuntimeError("OpenRouter unauthorized (check OPENROUTER_API_KEY)") from e
                if route.kind == "cloud_direct":
                    raise RuntimeError("OpenAI unauthorized (check OPENAI_API_KEY)") from e
            raise RuntimeError(f"LLM request failed (HTTP {status}){detail}") from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Provider request failed ({route.kind} {route.provider_name} @ {route.base_url}): "
                f"{type(e).__name__}: {e}"
            ) from e

    # OpenAI-compatible response: choices[0].message.content
    try:
        choice0 = (data.get("choices") or [])[0]
        msg = choice0.get("message") or {}
        content = msg.get("content")
        text = str(content or "")
    except Exception:
        text = ""

    provider_response_id: str | None = None
    try:
        rid = data.get("id")
        if isinstance(rid, str) and rid.strip():
            provider_response_id = rid.strip()
    except Exception:
        provider_response_id = None

    return text, provider_response_id


async def stream_chat_text(
    *,
    route: ProviderRoute,
    openrouter_cfg: OpenRouterConfig,
    system_prompt: str,
    user_message: str,
    images: list[ImageAttachment],
    temperature: float,
    max_tokens: int,
    context_text: str | None = None,
    context_chunks: list[ChunkMatch],
    timeout_s: float = 120.0,
    on_provider_response_id: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Stream chat response deltas (OpenAI-compatible chat completions stream)."""

    if context_text is not None:
        context_block = str(context_text or "").strip()
    else:
        context_block = _format_chunks_for_context(context_chunks)

    prompt = system_prompt if not context_block else f"{system_prompt}\n\n## Context\n{context_block}"
    messages = _build_messages(system_prompt=prompt, user_message=user_message, images=images)

    base_url = route.base_url.rstrip("/")
    url = (
        f"{base_url}/chat/completions"
        if route.kind in {"openrouter", "cloud_direct"}
        else f"{base_url}/v1/chat/completions"
    )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if route.kind == "openrouter":
        if not route.api_key:
            raise RuntimeError("OpenRouter enabled but OPENROUTER_API_KEY is not set")
        headers = _openrouter_headers(api_key=route.api_key, cfg=openrouter_cfg)
    if route.kind == "cloud_direct":
        if not route.api_key:
            raise RuntimeError("Cloud provider enabled but API key is not set")
        headers = _bearer_headers(api_key=route.api_key)

    payload: dict[str, Any] = {
        "model": route.model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True,
    }

    sent_provider_id = False
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    line = (raw_line or "").strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        return
                    try:
                        payload = json.loads(data_str)
                    except Exception:
                        continue
                    if not sent_provider_id and on_provider_response_id is not None:
                        try:
                            rid = payload.get("id")
                            if isinstance(rid, str) and rid.strip():
                                sent_provider_id = True
                                on_provider_response_id(rid.strip())
                        except Exception:
                            pass
                    try:
                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0].get("delta") or {}).get("content")
                        if isinstance(delta, str) and delta:
                            yield delta
                    except Exception:
                        continue
        except httpx.HTTPStatusError as e:
            status = int(getattr(e.response, "status_code", 0) or 0)
            if status == 401:
                if route.kind == "openrouter":
                    raise RuntimeError("OpenRouter unauthorized (check OPENROUTER_API_KEY)") from e
                if route.kind == "cloud_direct":
                    raise RuntimeError("OpenAI unauthorized (check OPENAI_API_KEY)") from e
            raise RuntimeError(f"LLM request failed (HTTP {status})") from e
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Provider request failed ({route.kind} {route.provider_name} @ {route.base_url}): "
                f"{type(e).__name__}: {e}"
            ) from e
