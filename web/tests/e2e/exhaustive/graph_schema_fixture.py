"""Keep the real local schema transport fixture alive for browser acceptance."""

from __future__ import annotations

import json
import signal
import threading

from tests.unit.test_graphrag_schema_transport import proposal_gateway


def main() -> None:
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    signal.signal(signal.SIGINT, lambda *_args: stopped.set())
    with proposal_gateway("valid") as (base_url, _requests):
        print(json.dumps({"base_url": base_url}), flush=True)
        stopped.wait()


if __name__ == "__main__":
    main()
