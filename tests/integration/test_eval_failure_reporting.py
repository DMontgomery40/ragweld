"""Real retrieval failures stay visible at eval and Promptfoo boundaries."""

import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from pydantic import TypeAdapter

from server.api.dataset import _dataset_path_for_corpus
from server.api.eval import router as eval_router
from server.api.generation_errors import generation_unavailable_http_exception
from server.chat.handler import ChatGenerationError
from server.config import load_config
from server.db.postgres import PostgresClient
from server.evaluation.promptfoo_runner import PromptfooTest, run_regression
from tests.api.test_search_reranker_fails_closed import (
    QUESTION,
    UNRESOLVABLE_ALIAS,
    _cleanup,
    _seeded_corpus,
)


def test_eval_run_declares_its_actual_generation_failure_envelope():
    failure = generation_unavailable_http_exception(
        ChatGenerationError("LLM returned an empty response during eval generation"),
        operation="Eval answer generation",
    )
    route = next(route for route in eval_router.routes if route.path == "/eval/run")
    declared_response = TypeAdapter(route.responses[failure.status_code]["model"])
    envelope = {"detail": failure.detail}

    parsed = declared_response.validate_python(envelope)

    assert parsed.detail.code == "generation_unavailable"
    assert parsed.model_dump(mode="json") == envelope


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_eval_run_reports_a_real_reranker_failure_as_typed_503(client):
    cfg = load_config()
    cfg.vector_search.enabled = False
    cfg.graph_search.enabled = False
    cfg.sparse_search.enabled = True
    cfg.evaluation.ragas_enabled = False
    cfg.reranking.reranker_mode = "cloud"
    cfg.reranking.reranker_cloud_model = UNRESOLVABLE_ALIAS
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    cid = await _seeded_corpus(pg, cfg)
    try:
        added = await client.post(
            f"/api/dataset?corpus_id={cid}",
            json={"entry_id": "failure", "question": QUESTION, "expected_paths": ["src/auth/login_controller.py"]},
        )
        assert added.status_code == 200, added.text
        response = await client.post("/api/eval/run", json={"repo_id": cid, "sample_size": 1})
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "reranker_failed"
        assert response.json()["detail"]["mode"] == "cloud"
        assert (await client.get(f"/api/eval/runs?corpus_id={cid}")).json()["runs"] == []
    finally:
        _dataset_path_for_corpus(cid).unlink(missing_ok=True)
        await _cleanup(pg, cid)
        await pg.disconnect()


@pytest.mark.requires_postgres
@pytest.mark.requires_model_gateway
def test_promptfoo_reports_real_api_failure_instead_of_grading_an_empty_answer(tmp_path):
    """Use the actual Ragweld HTTP app, actual Promptfoo CLI, and authenticated gateway."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    previous_port = os.environ.get("BACKEND_PORT")
    os.environ["BACKEND_PORT"] = str(port)
    process = None
    try:
        with (tmp_path / "api.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--lifespan", "off"],
                stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ),
            )
            deadline = time.monotonic() + 30
            with httpx.Client(timeout=1) as client:
                while True:
                    assert process.poll() is None, (tmp_path / "api.log").read_text()
                    try:
                        if client.get(f"http://127.0.0.1:{port}/api/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, "Private Ragweld API did not start"
                    time.sleep(0.05)
            cfg = load_config()
            cfg.chat.litellm.default_model = "openai.gpt-6-sol"
            cfg.evaluation.promptfoo_grader_model = "openai.gpt-6-sol"
            run = run_regression(
                cfg, repo_id=f"pytest_missing_corpus_{uuid4().hex}",
                tests=[PromptfooTest(
                    entry_id="missing",
                    question="In A11_MissionReport.pdf, what number vehicle was AS-506 in the Apollo Saturn V series, and what was its manned-mission rank?",
                    expected_answer="It was the sixth in the Apollo Saturn V series and the fourth manned Apollo Saturn V vehicle.",
                )],
                skipped_entries=0,
            )
            assert run.total == 1 and run.failed == 1 and run.passed == 0
            result = run.results[0]
            assert "HTTP call failed with status" in result.reason
            assert "404" in result.reason
            assert "empty" not in result.reason.lower()
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        if previous_port is None:
            os.environ.pop("BACKEND_PORT", None)
        else:
            os.environ["BACKEND_PORT"] = previous_port
