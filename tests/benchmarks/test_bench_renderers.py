from __future__ import annotations

from plotsrv.renderers.registry import render_any


def _make_large_markdown() -> str:
    blocks = []
    for i in range(300):
        blocks.append(
            f"# Heading {i}\n\n"
            f"Some paragraph text for section {i}.\n\n"
            f"- item one\n- item two\n- item three\n\n"
            f"```python\nprint('hello {i}')\n```\n"
        )
    return "\n".join(blocks)


def _make_large_html() -> str:
    parts = ["<div>"]
    for i in range(500):
        parts.append(
            f"<section><h2>Section {i}</h2><p>This is some html content {i}.</p></section>"
        )
    parts.append("</div>")
    return "".join(parts)


def _make_large_json() -> dict[str, object]:
    return {
        "items": [
            {
                "id": i,
                "name": f"item_{i}",
                "values": list(range(20)),
                "meta": {
                    "group": i % 10,
                    "flag": i % 2 == 0,
                    "text": "x" * 200,
                },
            }
            for i in range(500)
        ],
        "summary": {
            "count": 500,
            "description": "benchmark payload",
        },
    }


def _make_traceback_payload() -> dict[str, object]:
    frames = []
    for i in range(40):
        frames.append(
            {
                "filename": f"/tmp/module_{i}.py",
                "lineno": 100 + i,
                "function": f"func_{i}",
                "line": f"raise ValueError('bad value {i}')",
                "context_before": [f"line before {j}" for j in range(3)],
                "context_after": [f"line after {j}" for j in range(3)],
            }
        )
    return {
        "type": "traceback",
        "exc_type": "ValueError",
        "exc_msg": "Something went wrong",
        "frames": frames,
    }


def test_benchmark_render_markdown(benchmark) -> None:
    payload = _make_large_markdown()
    result = benchmark(
        lambda: render_any(payload, view_id="bench", kind_hint="markdown")
    )

    assert result.kind == "markdown"


def test_benchmark_render_html(benchmark) -> None:
    payload = _make_large_html()
    result = benchmark(lambda: render_any(payload, view_id="bench", kind_hint="html"))

    assert result.kind == "html"


def test_benchmark_render_json_tree(benchmark) -> None:
    payload = _make_large_json()
    result = benchmark(lambda: render_any(payload, view_id="bench", kind_hint="json"))

    assert result.kind == "json"


def test_benchmark_render_traceback(benchmark) -> None:
    payload = _make_traceback_payload()
    result = benchmark(
        lambda: render_any(payload, view_id="bench", kind_hint="traceback")
    )

    assert result.kind == "traceback"


def test_benchmark_render_text(benchmark) -> None:
    payload = "\n".join(f"log line {i}" for i in range(5000))
    result = benchmark(lambda: render_any(payload, view_id="bench", kind_hint="text"))

    assert result.kind == "text"
