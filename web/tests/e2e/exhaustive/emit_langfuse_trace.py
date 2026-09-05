"""Publish a synthetic telemetry span to the real Langfuse; no model or corpus data."""

from __future__ import annotations

import sys

from langfuse import Langfuse


def main() -> None:
    trace_id, base_url = sys.argv[1:]
    client = Langfuse(base_url=base_url, environment="acceptance")
    try:
        with client.start_as_current_observation(
            name="trace-link-acceptance",
            as_type="span",
            trace_context={"trace_id": trace_id},
        ):
            pass
        client.flush()
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
