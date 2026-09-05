from __future__ import annotations

import base64
import contextlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest
from docling.backend.html_backend import HTMLDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.backend_options import HTMLBackendOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult, InputDocument
from docling.datamodel.pipeline_options import PictureDescriptionApiOptions
from docling.document_converter import DocumentConverter, HTMLFormatOption
from docling.exceptions import OperationNotAllowed
from docling.models.factories import get_picture_description_factory
from docling.models.stages.picture_description.picture_description_api_model import (
    PictureDescriptionApiModel,
)
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    ImageRef,
    PictureMeta,
    Size,
)
from docling_core.types.doc.document import (
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    ProvenanceItem,
)
from PIL import Image
from pydantic import AnyUrl, ValidationError

from server.indexing import text_extractors
from server.indexing.docling_census import (
    CensusPictureModel,
    CensusPictureOptions,
    register_census_picture_model,
)
from server.indexing.text_extractors import (
    FigureGateway,
    docling_converter_for,
    extract_text_for_path,
)
from server.models.tribrid_config_model import IndexingFiguresConfig
from server.observability.run_census import (
    CensusDispatchDisabled,
    RunCensusScope,
    RunIdentity,
)
from tests.fixtures.pdf_builder import apollo_figure_pages
from tests.unit.test_figure_extraction_options import (
    owned_converter_cache,  # noqa: F401 - pytest fixture
)
from tests.unit.test_run_census import FileCheckpointStore


@pytest.fixture
def provider():
    calls = []
    stores = {}
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            session = self.headers.get("x-litellm-session-id")
            checkpoint = stores[session].read() if session in stores else None
            with lock:
                calls.append((self.path, payload, dict(self.headers), checkpoint))
                if len(calls) >= 2:
                    entered.set()
            if self.path in {"/held", "/timeout"}:
                release.wait(5)
            if self.path == "/disconnect":
                self.close_connection = True
                return
            status = 503 if self.path == "/failure" else 200
            body = json.dumps({
                "id": "synthetic-picture-completion", "created": 1,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "  Calibration rises linearly.  "}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            }).encode()
            if self.path.startswith("/structured/"):
                completion = json.loads(body)
                completion["choices"][0]["message"]["content"] = json.dumps({
                    "kind": "other", "summary": "A calibration curve is plotted against sensor input.",
                    "labels": ["Sensor input", "Calibration response"],
                })
                body = json.dumps(completion).encode()
            if self.path == "/failure":
                body = b'{"error":{"message":"synthetic service unavailable"}}'
            elif self.path == "/malformed":
                body = b"invalid json"
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, stores, entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def scope_for(tmp_path: Path, provider, session="figure-run-a"):
    store = FileCheckpointStore(tmp_path / f"{session}.json")
    scope = RunCensusScope(RunIdentity(session, "calibration-report", "figure_description"), store)
    provider[2][session] = store
    return scope, store


def options_for(provider, path="/success", timeout=2):
    return PictureDescriptionApiOptions(
        url=AnyUrl(provider[0] + path), timeout=timeout, concurrency=2,
        prompt="Describe the calibration curve, its axes, and visible limitations.",
        headers={"Authorization": "Bearer synthetic-only", "traceparent": "00-12345678901234567890123456789012-1234567890123456-01"},
        params={"model": "synthetic-vision", "max_completion_tokens": 48, "temperature": 0},
        classification_deny=["logo"], classification_min_confidence=0.5,
        picture_area_threshold=0.05, provenance="fixture-vision",
    )


def create_model(options, scope=None):
    register_census_picture_model()
    if scope is not None:
        options = CensusPictureOptions(**options.model_dump(), scope=scope)
    return get_picture_description_factory(allow_external_plugins=False).create_instance(
        options=options, enabled=True, enable_remote_services=True,
        artifacts_path=None, accelerator_options=AcceleratorOptions(),
    )


def pictures(count=2, skipped=False):
    doc = DoclingDocument(name="calibration-report")
    page_image = Image.new("RGB", (100, 100), "white")
    for x in range(10, 60):
        for y in range(20, 50):
            page_image.putpixel((x, y), (x, y, 200))
    doc.add_page(page_no=1, size=Size(width=100, height=100), image=ImageRef.from_pil(page_image, dpi=72))
    for _index in range(count):
        box = BoundingBox(l=10, t=20, r=60, b=50, coord_origin=CoordOrigin.TOPLEFT)
        item = doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 0)))
        item.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
            PictureClassificationPrediction(class_name="line_chart", confidence=0.9),
            PictureClassificationPrediction(class_name="logo", confidence=0.0001),
        ]))
    if skipped:
        logo = doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 0)))
        logo.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
            PictureClassificationPrediction(class_name="logo", confidence=0.95),
        ]))
        doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=2, b=2, coord_origin=CoordOrigin.TOPLEFT), charspan=(0, 0)))
    input_document = InputDocument(BytesIO(b"<html><body>Calibration report</body></html>"), InputFormat.HTML, HTMLDocumentBackend, filename="calibration.html")
    return ConversionResult(input=input_document, document=doc)


def describe(model, conversion):
    elements = [model.prepare_element(conversion, item) for item in conversion.document.pictures]
    assert all(element is not None for element in elements)
    return list(model(conversion.document, elements))


def test_official_factory_and_native_behavior_are_preserved(provider, tmp_path):
    scope, store = scope_for(tmp_path, provider)
    options = options_for(provider)
    native = create_model(options)
    adapted = create_model(options, scope)
    assert type(native) is PictureDescriptionApiModel and type(adapted) is CensusPictureModel
    assert CensusPictureModel.prepare_element is PictureDescriptionApiModel.prepare_element
    native_result = describe(native, pictures(skipped=True))
    adapted_result = describe(adapted, pictures(skipped=True))
    scope.finish_owner()
    assert len(native_result) == len(adapted_result) == 2
    assert len(provider[1]) == 4
    for native_item, adapted_item in zip(native_result, adapted_result, strict=True):
        assert native_item.meta == adapted_item.meta
        assert native_item.annotations == adapted_item.annotations
        assert adapted_item.meta.description.text == "Calibration rises linearly."
    assert provider[1][0][1] == provider[1][2][1]
    image_url = provider[1][2][1]["messages"][0]["content"][0]["image_url"]["url"]
    with Image.open(BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as image:
        assert image.size == (50, 30) and image.mode == "RGBA"
    for _, _, headers, observed in provider[1][2:]:
        assert observed.started_requests >= 1 and observed.inflight >= 1
        assert headers["x-litellm-session-id"] == headers["x-litellm-trace-id"] == scope.identity.session_id
        assert json.loads(headers["x-litellm-spend-logs-metadata"])["lane"] == "figure_description"
        assert headers["traceparent"] == options.headers["traceparent"]
    final = store.read()
    assert final.state == "closed" and final.started_requests == final.completed_requests == 2


@pytest.mark.parametrize(("path", "failed", "uncertain"), [
    ("/failure", 1, 0), ("/malformed", 0, 0), ("/disconnect", 0, 1), ("/timeout", 0, 1),
])
def test_http_and_description_failures_do_not_erase_attempts(provider, tmp_path, path, failed, uncertain):
    scope, store = scope_for(tmp_path, provider)
    model = create_model(options_for(provider, path, timeout=0.15), scope)
    result = describe(model, pictures(count=1))
    scope.finish_owner()
    assert result[0].meta.description.text == ""
    final = store.read()
    assert final.state == "closed" and final.started_requests == final.completed_requests == 1
    assert final.failed_requests == failed and final.uncertain_requests == uncertain


def test_held_nested_workers_survive_owner_completion_and_block_late_dispatch(provider, tmp_path):
    scope, store = scope_for(tmp_path, provider)
    model = create_model(options_for(provider, "/held"), scope)
    outer_lease = scope.producer_started()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(describe, model, pictures(count=4))
        future.add_done_callback(lambda _: outer_lease.close())
        try:
            assert provider[3].wait(3)
            scope.finish_owner()
            scope.disable_dispatch()
            held = store.read()
            assert held.owner_finished and held.state == "open"
            assert held.inflight == 2 and held.active_producers == 2
        finally:
            provider[4].set()
        with pytest.raises(CensusDispatchDisabled):
            future.result(timeout=3)
    final = store.read()
    assert len(provider[1]) == 2
    assert final.state == "closed" and final.inflight == final.active_producers == 0
    assert final.started_requests == final.completed_requests == 2


@pytest.mark.usefixtures("owned_converter_cache")
def test_bounded_converter_cache_keeps_two_run_contexts_distinct(provider, tmp_path):
    figures = IndexingFiguresConfig(enabled=True, describe=True, classify=False)

    def gateway(scope):
        return FigureGateway(provider[0], "synthetic-only", "z-ai.glm-5.3-flash", scope)
    scope_a, store_a = scope_for(tmp_path, provider, "figure-run-a")
    scope_b, store_b = scope_for(tmp_path, provider, "figure-run-b")
    first = docling_converter_for(figures, gateway(scope_a))
    assert docling_converter_for(figures, gateway(scope_a)) is first
    second = docling_converter_for(figures, gateway(scope_b))
    assert second is not first
    for converter, scope in ((first, scope_a), (second, scope_b)):
        scoped = converter.format_to_options[InputFormat.PDF].pipeline_options.picture_description_options
        assert scoped.scope is scope
        # Run an actual HTML conversion through Docling's same common enrichment
        # factory, avoiding PDF layout-model downloads in this bounded fixture.
        html_converter = DocumentConverter(format_options={InputFormat.HTML: HTMLFormatOption(pipeline_options=converter.format_to_options[InputFormat.PDF].pipeline_options, backend_options=HTMLBackendOptions(fetch_images=True))})
        image = BytesIO()
        Image.new("RGB", (80, 60), "blue").save(image, "PNG")
        document = tmp_path / f"{scope.identity.session_id}.html"
        document.write_text('<html><body><p>Calibration figure</p><img src="data:image/png;base64,' + base64.b64encode(image.getvalue()).decode() + '"/></body></html>')
        result = html_converter.convert(document)
        assert result.document.pictures[0].meta.description.text == "Calibration rises linearly."
        scope.finish_owner()
    assert store_a.read().started_requests == store_b.read().started_requests == 1
    assert [entry[2]["x-litellm-session-id"] for entry in provider[1]] == ["figure-run-a", "figure-run-b"]
    scope_c, _ = scope_for(tmp_path, provider, "figure-run-c")
    docling_converter_for(figures, gateway(scope_c))
    assert len(text_extractors._FIGURE_CONVERTERS) == 2
    assert first.format_to_options[InputFormat.PDF].pipeline_options.picture_description_options.scope is scope_a


def test_remote_service_guard_is_inherited_without_any_dispatch(provider, tmp_path):
    scope, store = scope_for(tmp_path, provider)
    register_census_picture_model()
    options = CensusPictureOptions(**options_for(provider).model_dump(), scope=scope)
    with pytest.raises(OperationNotAllowed):
        get_picture_description_factory(allow_external_plugins=False).create_instance(
            options=options, enabled=True, enable_remote_services=False,
            artifacts_path=None, accelerator_options=AcceleratorOptions(),
        )
    scope.finish_owner()
    assert not provider[1] and store.read().started_requests == 0


def test_scope_binding_is_fixed_and_stale_native_headers_cannot_override_it(provider, tmp_path):
    scope, store = scope_for(tmp_path, provider)
    other, _ = scope_for(tmp_path, provider, "other-run")
    options = options_for(provider)
    options.headers.update({
        "x-litellm-session-id": "old-run", "x-litellm-trace-id": "wrong-trace",
        "x-litellm-spend-logs-metadata": '{"run_id":"old-run","corpus_id":"foreign","lane":"semantic_kg"}',
    })
    scoped = CensusPictureOptions(**options.model_dump(), scope=scope)
    with pytest.raises(ValidationError):
        scoped.scope = other
    model = create_model(options, scope)
    describe(model, pictures(count=1))
    scope.finish_owner()
    headers = provider[1][0][2]
    assert headers["x-litellm-session-id"] == headers["x-litellm-trace-id"] == scope.identity.session_id
    assert json.loads(headers["x-litellm-spend-logs-metadata"]) == {
        "run_id": scope.identity.session_id, "corpus_id": "calibration-report", "lane": "figure_description",
    }
    assert store.read().started_requests == 1 and other.snapshot().started_requests == 0


def test_a_different_census_lane_cannot_claim_picture_requests(provider, tmp_path):
    scope = RunCensusScope(
        RunIdentity("wrong-lane", "calibration-report", "semantic_kg"),
        FileCheckpointStore(tmp_path / "wrong-lane.json"),
    )
    with pytest.raises(ValidationError, match="figure_description census lane"):
        create_model(options_for(provider), scope)
    assert not provider[1] and scope.snapshot().started_requests == 0


@pytest.mark.usefixtures("owned_converter_cache")
def test_real_pdf_extraction_uses_scoped_dispatch_and_retains_structured_figures(provider, tmp_path):
    scope, store = scope_for(tmp_path, provider)
    figures = IndexingFiguresConfig(enabled=True, describe=True, classify=True)
    gateway = FigureGateway(
        provider[0] + "/structured", "synthetic-only", "z-ai.glm-5.3-flash", scope,
    )
    extracted = extract_text_for_path(apollo_figure_pages(), figures=figures, gateway=gateway)
    scope.finish_owner()
    assert extracted is not None
    assert extracted.figures_described == len(provider[1]) == 2
    assert extracted.figures_failed == 0
    assert any(span.figure and span.figure.summary == "A calibration curve is plotted against sensor input." for span in extracted.spans)
    final = store.read()
    assert final.state == "closed" and final.started_requests == final.completed_requests == 2
    assert final.failed_requests == final.uncertain_requests == final.active_producers == 0
