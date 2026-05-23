from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore

from plotsrv.config_writer import (
    create_config_file,
    default_config_text,
    populate_freshness,
    populate_limits,
    populate_storage,
)
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
    assert "latest:" in text
    assert "restore_on_startup:" in text
    assert "restore_scope:" in text


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


def _write_views_file(root: Path) -> Path:
    p = root / "views.py"
    p.write_text(
        """
import plotsrv as ps

@ps.view(label="orders", section="etl")
def orders():
    return {"ok": True}

@ps.view(label="health", section="ops")
def health():
    return {"ok": True}
""".strip(),
        encoding="utf-8",
    )
    return p


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_populate_freshness_creates_file_and_views(tmp_path: Path) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"

    result = populate_freshness(
        path=cfg,
        target=target,
        expected_every="10s",
        warn_after="20s",
        overdue_after="30s",
    )

    assert result.created is True
    assert result.discovered_count == 2
    assert result.added_count == 2

    data = _load_yaml(cfg)
    sec = data["freshness-settings"]
    assert sec["enabled"] is True
    assert set(sec["views"]) == {"etl:orders", "ops:health"}
    assert sec["views"]["etl:orders"]["expected_every"] == "10s"


def test_populate_limits_adds_render_entries(tmp_path: Path) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"

    result = populate_limits(
        path=cfg,
        target=target,
        text="off",
        html="off",
        markdown="50000",
    )

    assert result.added_count == 2

    data = _load_yaml(cfg)
    views = data["limits"]["views"]
    assert views["etl:orders"]["render"] == {
        "text": "off",
        "html": "off",
        "markdown": "50000",
    }


def test_populate_storage_adds_storage_entries(tmp_path: Path) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"

    result = populate_storage(
        path=cfg,
        target=target,
        keep_last=5,
        min_store_interval="30s",
        max_snapshot_size_mb=12.5,
    )

    assert result.added_count == 2

    data = _load_yaml(cfg)
    sec = data["storage-settings"]
    assert sec["enabled"] is True
    assert sec["views"]["etl:orders"]["enabled"] is True
    assert sec["views"]["etl:orders"]["keep_last"] == 5
    assert sec["views"]["etl:orders"]["min_store_interval"] == "30s"
    assert sec["views"]["etl:orders"]["max_snapshot_size_mb"] == 12.5
    assert sec["latest"]["enabled"] is False
    assert sec["latest"]["restore_on_startup"] is True
    assert sec["latest"]["restore_scope"] == "discovered"


def test_populate_merge_preserves_existing_view(tmp_path: Path) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"
    cfg.write_text(
        """
freshness-settings:
  enabled: true
  views:
    etl:orders:
      expected_every: 5m
""".strip(),
        encoding="utf-8",
    )

    result = populate_freshness(path=cfg, target=target, mode="merge")

    assert result.added_count == 1
    assert result.preserved_count == 1

    data = _load_yaml(cfg)
    views = data["freshness-settings"]["views"]
    assert views["etl:orders"]["expected_every"] == "5m"
    assert "ops:health" in views


def test_populate_replace_replaces_existing_views(tmp_path: Path) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"
    cfg.write_text(
        """
freshness-settings:
  enabled: true
  views:
    old:view:
      expected_every: 5m
""".strip(),
        encoding="utf-8",
    )

    result = populate_freshness(path=cfg, target=target, mode="replace")

    assert result.replaced is True
    assert result.added_count == 2

    data = _load_yaml(cfg)
    views = data["freshness-settings"]["views"]
    assert set(views) == {"etl:orders", "ops:health"}


def test_cli_config_populate_limits(tmp_path: Path, capsys) -> None:
    target = _write_views_file(tmp_path)
    cfg = tmp_path / "plotsrv.yml"

    rc = cli_mod.main(
        [
            "config",
            "populate",
            "limits",
            str(target),
            "--config",
            str(cfg),
            "--text",
            "off",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Discovered 2 view(s)." in out
    assert cfg.exists()

    data = _load_yaml(cfg)
    assert data["limits"]["views"]["etl:orders"]["render"]["text"] == "off"


def test_populate_freshness_discovers_publish_view_calls(tmp_path: Path) -> None:
    target = tmp_path / "publish_views.py"
    target.write_text(
        """
import plotsrv as ps

def main():
    ps.publish_view(object(), label="orders", section="etl")
    ps.publish_view(object(), view_id="ops:health")
""".strip(),
        encoding="utf-8",
    )

    cfg = tmp_path / "plotsrv.yml"

    result = populate_freshness(
        path=cfg,
        target=target,
        expected_every="10s",
        warn_after="20s",
        overdue_after="30s",
    )

    assert result.created is True
    assert result.discovered_count == 2
    assert result.added_count == 2

    data = _load_yaml(cfg)
    views = data["freshness-settings"]["views"]
    assert set(views) == {"etl:orders", "ops:health"}
