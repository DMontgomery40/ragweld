"""System One: typed judgments with probabilities from a ``POST /v1/systemone`` endpoint.

Two backends speak the same contract: TypeSafe's hosted Jev (``https://api.typesafe.ai``,
Bearer ``TYPESAFE_API_KEY``) and a self-hosted Laya ``laya-serve`` (no credential), which
keeps Ragweld's judgments available offline. ``SystemOneConfig`` selects one; there is no
automatic switching between them.

The request/answer schemas below validate the provider boundary. No frontend consumes
them, so only ``SystemOneConfig`` (composed into ``TriBridConfig``) reaches TypeScript.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SystemOneProvider = Literal["typesafe", "laya"]

JsonInstructions = str | dict[str, Any] | list[Any]


class SystemOneConfig(BaseModel):
    """Which System One endpoint answers Ragweld's typed judgments, and how it is called."""

    provider: SystemOneProvider = Field(
        default="typesafe",
        description=(
            "System One backend: 'typesafe' calls TypeSafe's hosted Jev (TYPESAFE_API_KEY); "
            "'laya' calls a self-hosted laya-serve (offline, no credential). Both speak POST /v1/systemone."
        ),
    )
    typesafe_base_url: str = Field(
        default="https://api.typesafe.ai",
        min_length=1,
        description="API root of the TypeSafe endpoint used when provider='typesafe'.",
    )
    laya_base_url: str = Field(
        default="http://127.0.0.1:58180",
        min_length=1,
        description="API root of the self-hosted laya-serve used when provider='laya'.",
    )
    model: str = Field(
        default="jev-latest",
        min_length=1,
        description=(
            "Model named in every request. TypeSafe needs a Jev model id (jev-latest). laya-serve honours a "
            "checkpoint name (english, multilingual, typed-decisions) and routes any other value by language."
        ),
    )
    timeout_s: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="Total budget per System One call in seconds, including retries after 408/429/5xx.",
    )
    max_concurrency: int = Field(
        default=16,
        ge=1,
        le=64,
        description=(
            "Concurrent System One requests one caller (a rerank, a synthetic run) keeps in flight. "
            "TypeSafe allows 1,200 requests per minute per key."
        ),
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=8,
        description="Retries after a 408, 429 or 5xx (including 529 Overloaded) or a connection failure; 0 disables.",
    )


class SystemOneNoulCriteria(BaseModel):
    """What a yes (noul near 1) and a no (noul near 0) mean."""

    model_config = ConfigDict(extra="forbid")

    true: JsonInstructions
    false: JsonInstructions


class SystemOneNoul(BaseModel):
    """One yes/no question; the answer is the probability of yes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"] = "noul"
    instructions: JsonInstructions
    criteria: SystemOneNoulCriteria | None = None


class SystemOneRequest(BaseModel):
    """The ``POST /v1/systemone`` body."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    state: JsonInstructions
    questions: dict[str, SystemOneNoul] = Field(min_length=1)


class SystemOneNoulAnswer(BaseModel):
    """A Noul answer. Provider-specific extras (Laya's ``confidence``/``action``) are ignored."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)


class SystemOneUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class SystemOneResponse(BaseModel):
    """The ``POST /v1/systemone`` answer. Laya's ``routing`` block and other extras are ignored."""

    model_config = ConfigDict(extra="ignore")

    model: str
    answers: dict[str, SystemOneNoulAnswer]
    usage: SystemOneUsage = Field(default_factory=SystemOneUsage)
