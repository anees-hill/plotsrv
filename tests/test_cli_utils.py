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


def test_fmt_bytes_units() -> None:
    assert cli_mod._fmt_bytes(0) == "0 B"
    assert cli_mod._fmt_bytes(1) == "1 B"
    assert cli_mod._fmt_bytes(1023) == "1023 B"
    assert cli_mod._fmt_bytes(1024) == "1.0 KB"
    assert cli_mod._fmt_bytes(1024 * 1024) == "1.0 MB"
    assert cli_mod._fmt_bytes(-10) == "0 B"


def test_confirm_yes_no_and_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert cli_mod._confirm("Delete?") is True

    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert cli_mod._confirm("Delete?") is True

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert cli_mod._confirm("Delete?") is False

    def raise_eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert cli_mod._confirm("Delete?") is False


def test_view_id_for_defaults() -> None:
    dv = cli_mod.DiscoveredView(kind="artifact", label="", section=None)
    assert cli_mod._view_id_for(dv) == "default:default"


def test_include_exclude_helpers() -> None:
    dv = cli_mod.DiscoveredView(kind="artifact", label="plot-a", section="sec-a")

    assert cli_mod._is_included(dv, set()) is True
    assert cli_mod._is_included(dv, {"plot-a"}) is True
    assert cli_mod._is_included(dv, {"sec-a"}) is True
    assert cli_mod._is_included(dv, {"sec-a:plot-a"}) is True
    assert cli_mod._is_included(dv, {"other"}) is False

    assert cli_mod._is_excluded(dv, set()) is False
    assert cli_mod._is_excluded(dv, {"plot-a"}) is True
    assert cli_mod._is_excluded(dv, {"sec-a"}) is True
    assert cli_mod._is_excluded(dv, {"sec-a:plot-a"}) is True
    assert cli_mod._is_excluded(dv, {"other"}) is False


def test_with_text_anchor_header() -> None:
    assert cli_mod._with_text_anchor_header("abc", "head") == "abc"
    assert cli_mod._with_text_anchor_header("abc", "tail").startswith(
        "\ufeffPLOTSRV_ANCHOR=tail\n"
    )


def test_default_watch_read_mode_csv_head_else_tail(tmp_path: Path) -> None:
    csv = tmp_path / "x.csv"
    txt = tmp_path / "x.log"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    txt.write_text("hello\n", encoding="utf-8")

    assert cli_mod._default_watch_read_mode(csv) == "head"
    assert cli_mod._default_watch_read_mode(txt) == "tail"


def test_read_head_and_tail_bytes(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("abcdef", encoding="utf-8")

    assert cli_mod._read_head_bytes(p, max_bytes=3) == b"abc"
    assert cli_mod._read_tail_bytes(p, max_bytes=3) == b"def"


def test_read_csv_tail_with_header_returns_tail_when_header_already_present(
    tmp_path: Path,
) -> None:
    p = tmp_path / "small.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")

    out = cli_mod._read_csv_tail_with_header_bytes(p, max_bytes=1000)
    assert out == b"a,b\n1,2\n"
