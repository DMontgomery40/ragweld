"""Execution restrictions shared by gateway and direct-provider boundaries.

Historical records retain their original model identities. New configuration,
catalog publication and paid execution must obey the operator's model policy.
"""

from __future__ import annotations

import re

_GPT4_FAMILY = re.compile(r"(?:^|[/.:_-])(?:chat)?gpt[-_.]?4(?:o)?(?=$|[/.:_-])", re.IGNORECASE)


def ensure_model_allowed(model: str) -> None:
    """Reject GPT-4, GPT-4o, GPT-4.1 and dated/size/batch variants."""

    if _GPT4_FAMILY.search(str(model or "").strip()):
        raise ValueError("GPT-4-class models are blocked in Ragweld; select an allowed model.")
