from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_TEXT = """# plotsrv.yml
#
# Starter configuration for plotsrv.
# Use this file to control limits, rendering, storage, freshness, and security.

limits:
  watched_files:
    # Maximum bytes read from watched files.
    # Use "off" to read whole files.
    max_bytes: 5000000

  render:
    # Display limits for text-like rendered views.
    # Use "off" to disable render truncation.
    text: 1000000
    html: off
    markdown: off

  tables:
    max_rows: 10000
    max_columns: 200

table-settings:
  table_view_mode: rich
  max_table_rows_simple: 200
  max_table_rows_rich: 1000

artifact-render-settings:
  html_sanitize: false
  markdown_sanitize: true

render-settings:
  default:
    plot_dpi: 200
    plot_default_figsize_in: "12,6"
    plot_bbox_tight: true
    plot_pad_inches: 0.10

storage-settings:
  enabled: false
  root_dir: .plotsrv/store
  default_keep_last: 2
  max_snapshot_size_mb: 20

freshness-settings:
  enabled: false
  expected_every: 60s
  warn_after: 90s
  overdue_after: 180s

security-settings:
  tracebacks_enabled: false
"""


@dataclass(frozen=True, slots=True)
class ConfigCreateResult:
    path: Path
    created: bool
    overwritten: bool


def default_config_text() -> str:
    return DEFAULT_CONFIG_TEXT


def create_config_file(
    path: str | Path,
    *,
    force: bool = False,
) -> ConfigCreateResult:
    p = Path(path).expanduser().resolve()

    if p.exists() and not force:
        raise FileExistsError(f"Config file already exists: {p}")

    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")

    return ConfigCreateResult(
        path=p,
        created=not existed,
        overwritten=existed,
    )
