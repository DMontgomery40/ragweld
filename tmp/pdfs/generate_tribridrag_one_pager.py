from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class FontSpec:
    name: str
    size: float
    leading: float


def wrap_text(text: str, *, font: FontSpec, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font.name, font.size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def draw_heading(
    c: canvas.Canvas,
    text: str,
    *,
    x: float,
    y: float,
    font: FontSpec,
    color: colors.Color,
) -> float:
    c.setFont(font.name, font.size)
    c.setFillColor(color)
    c.drawString(x, y, text)
    return y - font.leading


def draw_paragraph(
    c: canvas.Canvas,
    text: str,
    *,
    x: float,
    y: float,
    font: FontSpec,
    color: colors.Color,
    max_width: float,
) -> float:
    c.setFont(font.name, font.size)
    c.setFillColor(color)
    for line in wrap_text(text, font=font, max_width=max_width):
        c.drawString(x, y, line)
        y -= font.leading
    return y


def draw_bullets(
    c: canvas.Canvas,
    bullets: list[str],
    *,
    x: float,
    y: float,
    font: FontSpec,
    color: colors.Color,
    max_width: float,
    bullet_indent: float = 10.0,
) -> float:
    c.setFont(font.name, font.size)
    c.setFillColor(color)
    for bullet in bullets:
        bullet_lines = wrap_text(
            bullet,
            font=font,
            max_width=max_width - bullet_indent,
        )
        if not bullet_lines:
            continue
        c.drawString(x, y, "-")
        c.drawString(x + bullet_indent, y, bullet_lines[0])
        y -= font.leading
        for continuation in bullet_lines[1:]:
            c.drawString(x + bullet_indent, y, continuation)
            y -= font.leading
        y -= 1.5
    return y


def main() -> None:
    out_path = Path("output/pdf/tribridrag_one_pager.pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = letter
    margin = 0.6 * inch
    gutter = 0.35 * inch
    col_width = (page_width - (2 * margin) - gutter) / 2
    x_left = margin
    x_right = margin + col_width + gutter

    title_font = FontSpec("Helvetica-Bold", 22, 26)
    tagline_font = FontSpec("Helvetica", 10.5, 13.5)
    heading_font = FontSpec("Helvetica-Bold", 11, 14)
    body_font = FontSpec("Helvetica", 9.5, 12)
    code_font = FontSpec("Courier", 8.5, 10.5)

    ink = colors.HexColor("#111827")
    muted = colors.HexColor("#374151")
    light = colors.HexColor("#6B7280")
    rule = colors.HexColor("#E5E7EB")

    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.setTitle("TriBridRAG - One-Page Summary")

    y = page_height - margin

    # Title + tagline (full width)
    c.setFillColor(ink)
    c.setFont(title_font.name, title_font.size)
    c.drawString(margin, y, "TriBridRAG")
    y -= title_font.leading

    c.setFillColor(muted)
    c.setFont(tagline_font.name, tagline_font.size)
    c.drawString(
        margin,
        y,
        "Production-grade Retrieval-Augmented Generation combining Vector, Sparse, and Graph search",
    )
    y -= tagline_font.leading + 6

    # Divider
    y -= 6
    c.setStrokeColor(rule)
    c.setLineWidth(1)
    c.line(margin, y, page_width - margin, y)
    y -= 12

    left_y = y
    right_y = y

    # Left column
    left_y = draw_heading(
        c,
        "What it is",
        x=x_left,
        y=left_y,
        font=heading_font,
        color=ink,
    )
    left_y = draw_paragraph(
        c,
        "A corpus-first RAG app that runs vector (pgvector), sparse/BM25 (PostgreSQL FTS), and graph (Neo4j) "
        "retrieval in parallel. It fuses and optionally reranks results, with a FastAPI backend and React "
        "TypeScript UI.",
        x=x_left,
        y=left_y + 2,
        font=body_font,
        color=muted,
        max_width=col_width,
    )
    left_y -= 6

    left_y = draw_heading(
        c,
        "Who it is for",
        x=x_left,
        y=left_y,
        font=heading_font,
        color=ink,
    )
    left_y = draw_paragraph(
        c,
        "Primary persona: developers/operators indexing and querying corpora via UI, API, or MCP. "
        "(Not found explicitly in repo.)",
        x=x_left,
        y=left_y + 2,
        font=body_font,
        color=muted,
        max_width=col_width,
    )
    left_y -= 6

    left_y = draw_heading(
        c,
        "What it does",
        x=x_left,
        y=left_y,
        font=heading_font,
        color=ink,
    )
    left_y = draw_bullets(
        c,
        [
            "Tri-brid retrieval: vector (pgvector), sparse (PostgreSQL FTS/BM25), graph (Neo4j traversal).",
            "Fusion via Reciprocal Rank Fusion (RRF) or weighted scoring.",
            "Optional reranking: local cross-encoder or cloud APIs (Cohere/Voyage/Jina).",
            "Corpus-first indexing: gitignore-aware loader, code-aware chunking, embeddings, graph builder.",
            "Full-stack UI + API: FastAPI backend; React+TypeScript+Zustand frontend; types generated from Pydantic.",
            "MCP server at /mcp with tools: search, answer, list_corpora.",
            "Observability, tracing, eval, and cost estimation (pricing from data/models.json).",
        ],
        x=x_left,
        y=left_y + 2,
        font=body_font,
        color=muted,
        max_width=col_width,
        bullet_indent=10,
    )

    # Right column
    right_y = draw_heading(
        c,
        "How it works (repo-backed)",
        x=x_right,
        y=right_y,
        font=heading_font,
        color=ink,
    )
    right_y = draw_bullets(
        c,
        [
            "Web UI (web/, React TS) calls FastAPI endpoints (/api/*).",
            "Config+API types: server/models/tribrid_config_model.py -> scripts/generate_types.py -> web/src/types/generated.ts.",
            "Indexing: corpus folder -> loader/chunker/embedder/graph_builder -> Postgres (pgvector + FTS) and Neo4j (entities+edges).",
            "Query: vector.py + sparse.py + graph.py run in parallel -> fusion.py -> (optional) rerank.py -> results/answers.",
            "Tracing: per-request debug info and ring-buffer trace store (server/services/traces.py).",
        ],
        x=x_right,
        y=right_y + 2,
        font=body_font,
        color=muted,
        max_width=col_width,
        bullet_indent=10,
    )
    right_y -= 4

    right_y = draw_heading(
        c,
        "How to run (minimal)",
        x=x_right,
        y=right_y,
        font=heading_font,
        color=ink,
    )

    # Small helper for code-like lines
    c.setFont(code_font.name, code_font.size)
    c.setFillColor(light)

    run_steps = [
        "cp .env.example .env  # add API keys",
        "./start.sh  # starts Postgres+Neo4j+API+UI",
    ]

    for step in run_steps:
        for line in wrap_text(step, font=code_font, max_width=col_width):
            c.drawString(x_right, right_y, line)
            right_y -= code_font.leading
        right_y -= 3

    right_y -= 2
    right_y = draw_paragraph(
        c,
        "UI: http://localhost:5173/web    API docs: http://localhost:8012/docs",
        x=x_right,
        y=right_y,
        font=body_font,
        color=light,
        max_width=col_width,
    )

    # Footer
    footer = "Source: README.md + repo tree (generated locally)."
    c.setFont("Helvetica", 8)
    c.setFillColor(light)
    c.drawString(margin, margin - 10, footer)

    c.showPage()
    c.save()


if __name__ == "__main__":
    main()
