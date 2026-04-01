from __future__ import annotations

from pathlib import Path

from plotsrv.discovery import discover_views


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_project(root: Path, *, n_files: int, views_per_file: int) -> None:
    dec_import = "from plotsrv.decorators import plot, table\n\n"

    for i in range(n_files):
        parts: list[str] = [dec_import]
        for j in range(views_per_file):
            parts.append(
                f"""
@plot(label="plot_{i}_{j}", section="sec_{i % 5}")
def plot_fn_{i}_{j}():
    return None

@table(label="table_{i}_{j}", section="sec_{i % 5}")
def table_fn_{i}_{j}():
    return None
""".strip()
            )
            parts.append("\n\n")
        _write_file(root / f"pkg/mod_{i}.py", "".join(parts))


def test_benchmark_discover_views_small(benchmark, tmp_path: Path) -> None:
    project_root = tmp_path / "small_project"
    _make_project(project_root, n_files=10, views_per_file=3)

    result = benchmark(discover_views, project_root)

    assert len(result) == 60


def test_benchmark_discover_views_medium(benchmark, tmp_path: Path) -> None:
    project_root = tmp_path / "medium_project"
    _make_project(project_root, n_files=40, views_per_file=5)

    result = benchmark(discover_views, project_root)

    assert len(result) == 400
