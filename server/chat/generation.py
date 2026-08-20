"""One OpenAI-compatible generation transport through LiteLLM."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from server.chat.provider_router import ProviderRoute
from server.models.chat_config import ImageAttachment
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import TraceCostSummary
from server.observability.costing import build_trace_cost_summary, extract_provider_cost
from server.observability.runtime import record_langfuse_generation, set_cost_summary, stage_span


@dataclass(slots=True)
class GenerationResult:
    text: str
    provider_response_id: str | None
    usage: dict[str, Any] | None = None
    cost_summary: TraceCostSummary | None = None
    debug_trace_id: str | None = None


def _format_chunks_for_context(chunks: list[ChunkMatch]) -> str:
    if not chunks:
        return "No relevant context found."
    parts: list[str] = []
    for chunk in chunks:
        header = f"## {chunk.file_path}:{int(chunk.start_line)}-{int(chunk.end_line)}"
        if chunk.language:
            header += f" ({chunk.language})"
        parts.append(f"{header}\n```\n{chunk.content}\n```")
    return "\n\n".join(parts)


def _attachment_to_openai_part(att: ImageAttachment, *, image_detail: str) -> dict[str, Any]:
    url = str(att.url) if att.url else f"data:{att.mime_type};base64,{att.base64}"
    detail = (image_detail or "auto").strip().lower()
    image_url: dict[str, Any] = {"url": url}
    if detail in {"auto", "low", "high"}:
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def _build_messages(
    *, system_prompt: str, user_message: str, images: list[ImageAttachment], image_detail: str
) -> list[dict[str, Any]]:
    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        content.extend(_attachment_to_openai_part(image, image_detail=image_detail) for image in images)
        user: dict[str, Any] = {"role": "user", "content": content}
    else:
        user = {"role": "user", "content": user_message}
    return [{"role": "system", "content": system_prompt}, user]


def _prompt_with_context(
    *, system_prompt: str, context_text: str | None, context_chunks: list[ChunkMatch]
) -> str:
    context = str(context_text or "").strip() if context_text is not None else _format_chunks_for_context(context_chunks)
    return system_prompt if not context else f"{system_prompt}\n\n## Context\n{context}"


def _headers(route: ProviderRoute) -> dict[str, str]:
    return {"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"}


def _url(route: ProviderRoute) -> str:
    return f"{route.base_url.rstrip('/')}/chat/completions"


def _usage(data: Any) -> dict[str, Any] | None:
    value = data.get("usage") if isinstance(data, dict) else None
    return value if isinstance(value, dict) else None


def _debug_trace_id(response: httpx.Response) -> str | None:
    for name in ("x-debug-trace-id", "x-request-id", "openai-request-id", "request-id"):
        value = response.headers.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return (response.text or "").strip()[:400]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"].strip()
        if isinstance(error, str):
            return error.strip()
        if isinstance(data.get("message"), str):
            return data["message"].strip()
    return ""


def _response_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("Gateway returned a non-object response")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("Gateway response missing choices[]")
    choice = choices[0]
    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(part.get("text"))
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part.get("text")
            ]
            if parts:
                return "\n".join(parts)
    if isinstance(choice.get("text"), str):
        return str(choice["text"])
    raise RuntimeError("Gateway response missing assistant content")


def _raise_status(error: httpx.HTTPStatusError) -> None:
    status = int(error.response.status_code)
    detail = _error_detail(error.response)
    if status == 401:
        raise RuntimeError("LiteLLM unauthorized (check LITELLM_API_KEY)") from error
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(f"LiteLLM request failed (HTTP {status}){suffix}") from error


async def generate_chat_text(
    *,
    route: ProviderRoute,
    system_prompt: str,
    user_message: str,
    images: list[ImageAttachment],
    image_detail: str = "auto",
    temperature: float,
    max_tokens: int,
    context_text: str | None = None,
    context_chunks: list[ChunkMatch],
    timeout_s: float = 120.0,
) -> GenerationResult:
    """Generate one non-streaming response through LiteLLM."""

    prompt = _prompt_with_context(
        system_prompt=system_prompt, context_text=context_text, context_chunks=context_chunks
    )
    payload = {
        "model": route.model,
        "messages": _build_messages(
            system_prompt=prompt,
            user_message=user_message,
            images=images,
            image_detail=image_detail,
        ),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    with stage_span(
        "generation.gateway_call", provider_name="LiteLLM", provider_kind="litellm", model=route.model
    ):
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            try:
                response = await client.post(_url(route), headers=_headers(route), json=payload)
                response.raise_for_status()
                data: Any = response.json()
            except httpx.HTTPStatusError as error:
                _raise_status(error)
                raise AssertionError("unreachable")
            except httpx.RequestError as error:
                raise RuntimeError(
                    f"LiteLLM request failed at {route.base_url}: {type(error).__name__}: {error}"
                ) from error

        try:
            text = _response_text(data)
        except Exception as error:
            raise RuntimeError(f"LiteLLM response parse failed: {error}") from error
        usage = _usage(data)
        provider_cost_usd = extract_provider_cost(data)
        cost = build_trace_cost_summary(
            provider="LiteLLM", model=route.model, usage=usage, provider_cost_usd=provider_cost_usd
        )
        trace_id = _debug_trace_id(response)
        set_cost_summary(cost)
        record_langfuse_generation(
            name="chat.generation",
            model=route.model,
            input_payload={"system_prompt": prompt, "user_message": user_message},
            output_text=text,
            usage_details=usage,
            cost_details=cost.model_dump(mode="json", by_alias=True),
            metadata={"provider_kind": "litellm", "provider_name": "LiteLLM", "debug_trace_id": trace_id},
        )

    response_id = data.get("id") if isinstance(data.get("id"), str) else None
    return GenerationResult(
        text=text,
        provider_response_id=response_id,
        usage=usage,
        cost_summary=cost,
        debug_trace_id=trace_id,
    )


async def stream_chat_text(
    *,
    route: ProviderRoute,
    system_prompt: str,
    user_message: str,
    images: list[ImageAttachment],
    image_detail: str = "auto",
    temperature: float,
    max_tokens: int,
    context_text: str | None = None,
    context_chunks: list[ChunkMatch],
    timeout_s: float = 120.0,
    on_provider_response_id: Callable[[str], None] | None = None,
    on_usage: Callable[[dict[str, Any]], None] | None = None,
    on_debug_trace_id: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Stream OpenAI Chat Completions deltas through LiteLLM."""

    prompt = _prompt_with_context(
        system_prompt=system_prompt, context_text=context_text, context_chunks=context_chunks
    )
    payload = {
        "model": route.model,
        "messages": _build_messages(
            system_prompt=prompt,
            user_message=user_message,
            images=images,
            image_detail=image_detail,
        ),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    sent_response_id = False
    streamed_text = ""
    captured_usage: dict[str, Any] | None = None
    captured_trace_id: str | None = None
    with stage_span(
        "generation.gateway_stream", provider_name="LiteLLM", provider_kind="litellm", model=route.model
    ):
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            try:
                async with client.stream("POST", _url(route), headers=_headers(route), json=payload) as response:
                    if response.is_error:
                        await response.aread()
                    response.raise_for_status()
                    captured_trace_id = _debug_trace_id(response)
                    if captured_trace_id and on_debug_trace_id:
                        on_debug_trace_id(captured_trace_id)
                    async for raw_line in response.aiter_lines():
                        line = (raw_line or "").strip()
                        if not line.startswith("data:"):
                            continue
                        encoded = line[len("data:") :].strip()
                        if encoded == "[DONE]":
                            break
                        try:
                            event = json.loads(encoded)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        if event.get("error"):
                            raise RuntimeError(str(event["error"]))
                        response_id = event.get("id")
                        if (
                            not sent_response_id
                            and isinstance(response_id, str)
                            and response_id.strip()
                            and on_provider_response_id
                        ):
                            sent_response_id = True
                            on_provider_response_id(response_id.strip())
                        event_usage = _usage(event)
                        if event_usage is not None:
                            captured_usage = event_usage
                            if on_usage:
                                on_usage(event_usage)
                        choices = event.get("choices")
                        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                            continue
                        delta = choices[0].get("delta")
                        content = delta.get("content") if isinstance(delta, dict) else None
                        if isinstance(content, str) and content:
                            streamed_text += content
                            yield content
            except httpx.HTTPStatusError as error:
                _raise_status(error)
                raise AssertionError("unreachable")
            except httpx.RequestError as error:
                raise RuntimeError(
                    f"LiteLLM stream failed at {route.base_url}: {type(error).__name__}: {error}"
                ) from error

        if not streamed_text:
            raise RuntimeError("LiteLLM stream produced no content")
        cost = build_trace_cost_summary(
            provider="LiteLLM", model=route.model, usage=captured_usage, provider_cost_usd=None
        )
        set_cost_summary(cost)
        record_langfuse_generation(
            name="chat.generation.stream",
            model=route.model,
            input_payload={"system_prompt": prompt, "user_message": user_message},
            output_text=streamed_text,
            usage_details=captured_usage,
            cost_details=cost.model_dump(mode="json", by_alias=True),
            metadata={
                "provider_kind": "litellm",
                "provider_name": "LiteLLM",
                "debug_trace_id": captured_trace_id,
            },
        )
