"""A local OpenAI-compatible gateway for the chat streaming specs (no paid model).

The chat perf, scroll-landing, navigation-continuity and failed-feedback specs need an answer
whose size, shape and pacing are pinned, so a render-cost number means the same thing on every
run. This fixture streams a scripted markdown answer through the real Ragweld API: the spec
patches its own pytest_ corpus's ``chat.litellm.base_url`` to this server (the API under test
must resolve the gateway from corpus config, i.e. run without ``LITELLM_BASE_URL``).

Token = one streamed delta. The answer is cut into deltas of at most four word characters (a
rough BPE stand-in) and paced at ``tokens_per_second``, each delta written and flushed as its
own SSE event, the way a provider relays tokens.

Control plane (``/__fixture__/...``):
  POST scenario  {"scenario": "long"|"medium"|"short"|"fail", "tokens_per_second": n}
  GET  state     request counters and the last model asked for
  GET  answer    the answer text and token count of the current scenario
  POST/GET rum   a Faro collector stand-in (``/collect``) whose payloads can be read back

Prints one JSON line ``{"base_url": ".../v1"}`` when listening. Stdlib only.
"""

from __future__ import annotations

import json
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_RE = re.compile(r"\s*\w{1,4}|\s*[^\w\s]|\s+")

_PY_BLOCK = '''```python
from dataclasses import dataclass
from statistics import mean, pstdev


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    day: int
    kpa: float


def drift_per_day(readings: list[Reading]) -> dict[str, float]:
    """Least-squares drift for each sensor, in kPa per day."""
    by_sensor: dict[str, list[Reading]] = {}
    for reading in readings:
        by_sensor.setdefault(reading.sensor_id, []).append(reading)
    drift: dict[str, float] = {}
    for sensor_id, rows in by_sensor.items():
        days = [row.day for row in rows]
        values = [row.kpa for row in rows]
        mean_day, mean_value = mean(days), mean(values)
        numerator = sum((d - mean_day) * (v - mean_value) for d, v in zip(days, values))
        denominator = sum((d - mean_day) ** 2 for d in days) or 1.0
        drift[sensor_id] = numerator / denominator
    return drift


def needs_recalibration(drift: dict[str, float], limit_kpa: float, interval_days: int) -> list[str]:
    """Sensors whose projected drift over one interval exceeds the limit."""
    flagged = [sensor for sensor, slope in drift.items() if abs(slope) * interval_days > limit_kpa]
    return sorted(flagged)


def spread(values: list[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0
```
'''

_TS_BLOCK = '''```typescript
type CalibrationWindow = {
  sensorId: string;
  lastCalibratedAt: string;
  intervalDays: number;
  driftKpaPerDay: number;
};

type ScheduleEntry = { sensorId: string; dueAt: Date; urgent: boolean };

const MS_PER_DAY = 86_400_000;

export function scheduleRecalibration(windows: CalibrationWindow[], limitKpa: number, now = new Date()): ScheduleEntry[] {
  return windows
    .map((window) => {
      const last = new Date(window.lastCalibratedAt).getTime();
      const dueAt = new Date(last + window.intervalDays * MS_PER_DAY);
      const projected = Math.abs(window.driftKpaPerDay) * window.intervalDays;
      const urgent = projected > limitKpa || dueAt.getTime() <= now.getTime();
      return { sensorId: window.sensorId, dueAt, urgent };
    })
    .sort((a, b) => Number(b.urgent) - Number(a.urgent) || a.dueAt.getTime() - b.dueAt.getTime());
}

export function formatEntry(entry: ScheduleEntry): string {
  const day = entry.dueAt.toISOString().slice(0, 10);
  return `${entry.sensorId.padEnd(8)} ${day}${entry.urgent ? '  URGENT' : ''}`;
}

export function summarize(entries: ScheduleEntry[]): { urgent: number; total: number } {
  return { urgent: entries.filter((entry) => entry.urgent).length, total: entries.length };
}
```
'''

_SENSORS = [
    ("PS-101", 90, "0.012", "within limit"),
    ("PS-102", 90, "0.019", "within limit"),
    ("PS-103", 60, "0.044", "recalibrate"),
    ("PS-104", 90, "0.008", "within limit"),
    ("PS-105", 30, "0.071", "recalibrate"),
    ("PS-106", 90, "0.015", "within limit"),
    ("PS-107", 60, "0.027", "watch"),
    ("PS-108", 90, "0.011", "within limit"),
    ("PS-109", 45, "0.052", "recalibrate"),
    ("PS-110", 90, "0.009", "within limit"),
    ("PS-111", 60, "0.031", "watch"),
    ("PS-112", 90, "0.014", "within limit"),
]

_TOPICS = [
    "the tidal pressure baseline",
    "the thermal soak before each reading",
    "the reference gauge certificate",
    "the humidity correction table",
    "the logger clock offset",
    "the manifold leak check",
    "the zero-point capture at slack water",
    "the span check against the dead-weight tester",
]

_CLAUSES = [
    "drifts slowly enough that a ninety day interval is still defensible",
    "shows a step change after every maintenance visit, which points at handling rather than ageing",
    "is the dominant error term once the rig has been running for more than a week",
    "was recorded inconsistently before the procedure revision, so older runs need a manual review",
    "matches the vendor figure within the stated uncertainty on every sensor but two",
    "should be logged with the operator initials so a later audit can trace each adjustment",
]


def _paragraph(seed: int) -> str:
    sentences = []
    for offset in range(4):
        topic = _TOPICS[(seed + offset * 3) % len(_TOPICS)]
        clause = _CLAUSES[(seed * 5 + offset) % len(_CLAUSES)]
        sentences.append(f"On this rig, {topic} {clause}.")
    return " ".join(sentences)


def _table() -> str:
    rows = ["| Sensor | Interval (days) | Drift (kPa/day) | Status |", "|---|---:|---:|---|"]
    rows += [f"| {s} | {i} | {d} | {st} |" for s, i, d, st in _SENSORS]
    return "\n".join(rows) + "\n"


def long_answer() -> str:
    parts = [
        "# Calibration review: pressure sensors on the acceptance rig\n",
        _paragraph(1) + "\n",
        "## Findings\n",
        "\n".join(f"- {_TOPICS[i].capitalize()} {_CLAUSES[i % len(_CLAUSES)]}." for i in range(6)) + "\n",
        _paragraph(2) + "\n",
        "## Procedure\n",
        "\n".join(f"{n}. Record {_TOPICS[(n + 2) % len(_TOPICS)]} before the span check." for n in range(1, 6)) + "\n",
        "The drift estimate below is what the review used to rank the sensors:\n",
        _PY_BLOCK,
        _paragraph(3) + "\n",
        "## Measurements\n",
        _table(),
        _paragraph(4) + "\n",
        "## Scheduling\n",
        _paragraph(5) + "\n",
        _TS_BLOCK,
    ]
    seed = 6
    while sum(len(p) for p in parts) < 13_200:
        parts.append(f"### Note {seed - 5}\n")
        parts.append(_paragraph(seed) + "\n")
        seed += 1
    parts.append("End of calibration report.\n")
    return "\n".join(parts)


def medium_answer() -> str:
    return "\n".join(
        [
            "## Short calibration summary\n",
            _paragraph(11) + "\n",
            _paragraph(12) + "\n",
            "- " + _CLAUSES[0].capitalize() + ".\n- " + _CLAUSES[1].capitalize() + ".\n",
            _paragraph(13) + "\n",
            "End of calibration summary.\n",
        ]
    )


def short_answer() -> str:
    return "The acceptance rig recalibrates its pressure sensors every **90 days**; PS-105 is due first.\n"


SCENARIOS = {"long": long_answer(), "medium": medium_answer(), "short": short_answer()}
DEFAULT_RATES = {"long": 200.0, "medium": 40.0, "short": 200.0}


def tokenize(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(text)
    assert "".join(tokens) == text, "tokenizer must be lossless"
    return tokens


class _State:
    lock = threading.Lock()
    scenario = "long"
    tokens_per_second: float | None = None
    received = 0
    completed = 0
    stream_requests = 0
    last_model: str | None = None
    rum: list[object] = []
    models: list[str] = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, obj: object, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {"raw": raw.decode("utf-8", errors="replace")}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler contract
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/models"):
            return self._json({"object": "list", "data": [{"id": m, "object": "model"} for m in _State.models]})
        if self.path.startswith("/__fixture__/state"):
            with _State.lock:
                return self._json(
                    {
                        "scenario": _State.scenario,
                        "received": _State.received,
                        "stream_requests": _State.stream_requests,
                        "completed": _State.completed,
                        "last_model": _State.last_model,
                    }
                )
        if self.path.startswith("/__fixture__/answer"):
            with _State.lock:
                scenario = _State.scenario
            text = SCENARIOS.get(scenario, "")
            return self._json({"scenario": scenario, "text": text, "tokens": len(tokenize(text)) if text else 0})
        if self.path.startswith("/__fixture__/rum"):
            with _State.lock:
                return self._json({"payloads": list(_State.rum)})
        return self._json({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/__fixture__/scenario"):
            payload = self._read_json()
            scenario = str(payload.get("scenario") or "long")
            if scenario not in SCENARIOS and scenario != "fail":
                return self._json({"error": f"unknown scenario {scenario}"}, 400)
            with _State.lock:
                _State.scenario = scenario
                tps = payload.get("tokens_per_second")
                _State.tokens_per_second = float(tps) if tps else None
            return self._json({"ok": True, "scenario": scenario})
        if self.path.startswith("/__fixture__/reset"):
            with _State.lock:
                _State.received = _State.completed = _State.stream_requests = 0
                _State.rum = []
            return self._json({"ok": True})
        if self.path.startswith("/collect") or self.path.startswith("/__fixture__/rum"):
            payload = self._read_json()
            with _State.lock:
                _State.rum.append(payload)
            return self._json({"ok": True}, 202)
        if self.path.endswith("/chat/completions"):
            return self._completion(self._read_json())
        return self._json({"error": {"message": f"fixture has no route {self.path}"}}, 404)

    def _completion(self, payload: dict) -> None:
        with _State.lock:
            _State.received += 1
            _State.last_model = str(payload.get("model") or "") or None
            scenario = _State.scenario
            rate = _State.tokens_per_second or DEFAULT_RATES.get(scenario, 200.0)
            if payload.get("stream"):
                _State.stream_requests += 1
        if scenario == "fail":
            return self._json({"error": {"message": "fixture upstream failure", "type": "server_error", "code": 500}}, 500)
        text = SCENARIOS[scenario]
        if not payload.get("stream"):
            self._json(
                {
                    "id": "chatcmpl-fixture",
                    "object": "chat.completion",
                    "model": payload.get("model") or "fixture",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 40, "completion_tokens": len(tokenize(text)), "total_tokens": 40 + len(tokenize(text))},
                }
            )
            with _State.lock:
                _State.completed += 1
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        tokens = tokenize(text)
        started = time.monotonic()
        try:
            for index, token in enumerate(tokens):
                due = started + index / rate
                pause = due - time.monotonic()
                if pause > 0:
                    time.sleep(pause)
                self._event({"choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]})
            self._event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            self._event({"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": len(tokens), "total_tokens": 40 + len(tokens)}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            with _State.lock:
                _State.completed += 1
        except (BrokenPipeError, ConnectionResetError):
            return

    def _event(self, chunk: dict) -> None:
        body = {"id": "chatcmpl-fixture", "object": "chat.completion.chunk", **chunk}
        self.wfile.write(f"data: {json.dumps(body)}\n\n".encode())
        self.wfile.flush()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    _State.models = [m for m in sys.argv[2:] if m] or ["openai.gpt-5.6-luna"]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    signal.signal(signal.SIGINT, lambda *_args: stopped.set())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, bound = server.server_address[:2]
    print(json.dumps({"base_url": f"http://{host}:{bound}/v1"}), flush=True)
    stopped.wait()
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    main()
