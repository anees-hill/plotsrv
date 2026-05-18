from __future__ import annotations

from pathlib import Path

import pytest

import plotsrv.cli as cli_mod
from plotsrv.config_writer import create_config_file, default_config_text


def test_default_config_text_contains_expected_sections() -> None:
    text = default_config_text()

    assert "limits:" in text
    assert "watched_files:" in text
    assert "render:" in text
    assert "tables:" in text
    assert "table-settings:" in text
    assert "storage-settings:" in text
    assert "freshness-settings:" in text
    assert "security-settings:" in text


def test_create_config_file_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "plotsrv.yml"

    result = create_config_file(p)

    assert result.path == p.resolve()
    assert result.created is True
    assert result.overwritten is False
    assert p.exists()
    assert "limits:" in p.read_text(encoding="utf-8")


def test_create_config_file_refuses_existing_without_force(tmp_path: Path) -> None:
    p = tmp_path / "plotsrv.yml"
    p.write_text("existing: true\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_config_file(p)

    assert p.read_text(encoding="utf-8") == "existing: true\n"


def test_create_config_file_overwrites_existing_with_force(tmp_path: Path) -> None:
    p = tmp_path / "plotsrv.yml"
    p.write_text("existing: true\n", encoding="utf-8")

    result = create_config_file(p, force=True)

    assert result.created is False
    assert result.overwritten is True
    assert "limits:" in p.read_text(encoding="utf-8")


def test_cli_config_create_creates_file(tmp_path: Path, capsys) -> None:
    p = tmp_path / "plotsrv.yml"

    rc = cli_mod.main(["config", "create", "--config", str(p)])

    assert rc == 0
    assert p.exists()
    out = capsys.readouterr().out
    assert "Created config file:" in out


def test_cli_config_create_refuses_existing_without_force(
    tmp_path: Path,
    capsys,
) -> None:
    p = tmp_path / "plotsrv.yml"
    p.write_text("existing: true\n", encoding="utf-8")

    rc = cli_mod.main(["config", "create", "--config", str(p)])

    assert rc == 2
    assert p.read_text(encoding="utf-8") == "existing: true\n"

    err = capsys.readouterr().err
    assert "already exists" in err
    assert "--force" in err


def test_cli_config_create_overwrites_with_force(tmp_path: Path, capsys) -> None:
    p = tmp_path / "plotsrv.yml"
    p.write_text("existing: true\n", encoding="utf-8")

    rc = cli_mod.main(["config", "create", "--config", str(p), "--force"])

    assert rc == 0
    assert "limits:" in p.read_text(encoding="utf-8")

    out = capsys.readouterr().out
    assert "Overwrote config file:" in out
