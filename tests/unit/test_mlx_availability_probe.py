from __future__ import annotations

import subprocess
import sys


def test_mlx_availability_probe_cannot_abort_the_calling_process() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from server.retrieval.mlx_qwen3 import mlx_is_available; "
                "first = mlx_is_available(); second = mlx_is_available(); "
                "assert isinstance(first, bool) and second is first; print(first)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() in {"True", "False"}
