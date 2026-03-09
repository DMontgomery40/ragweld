from __future__ import annotations

import warnings

from server.api.prompts import _build_prompts_payload
from server.models.tribrid_config_model import TriBridConfig


def test_build_prompts_payload_avoids_instance_model_fields_deprecation() -> None:
    cfg = TriBridConfig()

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        _build_prompts_payload(cfg)

    bad = [w for w in captured if "model_fields" in str(w.message)]
    assert bad == []
