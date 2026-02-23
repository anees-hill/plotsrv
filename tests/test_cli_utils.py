# tests/test_cli_utils.py
from __future__ import annotations

from pathlib import Path

import pytest

import plotsrv.cli as cli_mod


def test_norm_tokens_splits_commas_and_strips() -> None:
    raw = [" a, b ", "c", "", "  ", "d,e", None]  # type: ignore[list-item]
    assert cli_mod._norm_tokens(raw) == {"a", "b", "c", "d", "e"}


def test_resolve_module_part() -> None:
    assert cli_mod._resolve_module_part("pkg.mod:fn") == "pkg.mod"
    assert cli_mod._resolve_module_part("pkg.mod") == "pkg.mod"
    assert cli_mod._resolve_module_part("  pkg.mod:fn  ") == "pkg.mod"


def test_read_csv_tail_with_header_bytes_prepends_header(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    header = "a,b,c\n"
    body_lines = [f"{i},{i+1},{i+2}\n" for i in range(200)]
    p.write_text(header + "".join(body_lines), encoding="utf-8")

    out = cli_mod._read_csv_tail_with_header_bytes(p, max_bytes=120)

    norm = out.replace(b"\r\n", b"\n")
    assert norm.startswith(b"a,b,c\n")
    assert b"," in norm
    assert b"\n" in norm


def test_resolve_scan_root_for_passive_path_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "src"
    root.mkdir()

    monkeypatch.chdir(tmp_path)
    assert cli_mod._resolve_scan_root_for_passive("src") == str(root.resolve())
