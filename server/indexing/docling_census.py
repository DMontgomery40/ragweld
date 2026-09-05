"""Docling picture HTTP census using the official model and factory extension."""
from __future__ import annotations

import base64
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import ClassVar, Literal

import httpx
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import OpenAiApiResponse
from docling.datamodel.pipeline_options import (
    PictureDescriptionApiOptions,
    PictureDescriptionBaseOptions,
)
from docling.models.factories import get_picture_description_factory
from docling.models.stages.picture_description.picture_description_api_model import (
    PictureDescriptionApiModel,
)
from PIL import Image
from pydantic import ConfigDict, Field, ValidationError, model_validator

from server.observability.run_census import CensusTransport, RunCensusScope


class CensusPictureOptions(PictureDescriptionApiOptions):
    # Docling deliberately registers options by exact class. Its concrete API
    # subtype annotates kind as Literal["api"], although extension kinds differ.
    kind: ClassVar[Literal["ragweld_census_api"]] = "ragweld_census_api"  # type: ignore[assignment]
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    scope: RunCensusScope = Field(exclude=True, repr=False)

    @model_validator(mode="after")
    def _require_figure_lane(self) -> CensusPictureOptions:
        if self.scope.identity.lane != "figure_description":
            raise ValueError("Picture descriptions require the figure_description census lane")
        return self


class CensusPictureModel(PictureDescriptionApiModel):
    def __init__(
        self, enabled: bool, enable_remote_services: bool,
        artifacts_path: Path | str | None, options: CensusPictureOptions,
        accelerator_options: AcceleratorOptions,
    ) -> None:
        super().__init__(
            enabled=enabled, enable_remote_services=enable_remote_services,
            artifacts_path=artifacts_path, options=options,
            accelerator_options=accelerator_options,
        )
        self._scope = options.scope

    @classmethod
    def get_options_type(cls) -> type[PictureDescriptionBaseOptions]:
        return CensusPictureOptions

    def _annotate_images(self, images: Iterable[Image.Image]) -> Iterable[str]:
        pictures = list(images)
        if not pictures:
            return
        # Capture the explicit scope on this model, rather than contextvars that
        # disappear in Docling's nested ThreadPoolExecutor. The lease outlives all
        # workers even if a consumer closes the generator or a worker raises.
        lease = self._scope.producer_started()
        try:
            with httpx.Client(
                transport=CensusTransport(self._scope), trust_env=False,
                timeout=self.options.timeout, follow_redirects=False,
            ) as client:
                def describe(image: Image.Image) -> str:
                    return self._request_image(client, image)

                with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    yield from executor.map(describe, pictures)
        finally:
            lease.close()

    def _request_image(self, client: httpx.Client, image: Image.Image) -> str:
        # This is the small requests-only seam in Docling's api_image_request.
        # Crop/filter/RGB handling and annotation remain entirely inherited.
        buffer = BytesIO()
        try:
            image.copy().convert("RGBA").save(buffer, "PNG")
        except (OSError, ValueError):
            return ""
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            {"type": "text", "text": self.options.prompt},
        ]}]
        payload = {"messages": messages, **self.options.params}
        try:
            response = client.post(str(self.options.url), headers=self.options.headers, json=payload)
            # Preserve the native parser/empty-description outcome. Its stock
            # helper also attempts parsing non-2xx responses before returning "".
            parsed = OpenAiApiResponse.model_validate_json(response.content)
            return str(parsed.choices[0].message.content).strip()
        except (httpx.HTTPError, ValidationError, IndexError):
            return ""
        # CensusPersistenceError and CensusDispatchDisabled intentionally escape:
        # an unacknowledged dispatch must never look like a completed description.


_REGISTRATION_LOCK = threading.Lock()


def register_census_picture_model() -> None:
    """Use Docling's public registration API without overriding a stock class."""
    factory = get_picture_description_factory(allow_external_plugins=False)
    with _REGISTRATION_LOCK:
        existing = factory.classes.get(CensusPictureOptions)
        if existing is None:
            factory.register(CensusPictureModel, "ragweld", __name__)
        elif existing is not CensusPictureModel:
            raise RuntimeError("Census picture options already have a different registered owner")
