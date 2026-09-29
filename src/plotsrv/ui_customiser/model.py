"""One bounded UI draft, reusing the production model and reviewed YAML writer."""

from __future__ import annotations

from dataclasses import replace
import difflib
from pathlib import Path
import secrets

import yaml

from .. import settings
from ..ui_config import (
    load_ui_settings,
    _icon_link_url,
    DEFAULT_LOGO_URL,
    DEFAULT_FAVICON_URL,
)
from ..config_wizard.draft import _load_bounded
from ..config_wizard.saving import (
    Review,
    SaveError,
    narrow_yaml,
    read_snapshot,
    scoped_path,
    save,
)
from .uploads import Images

# Only supported chrome controls. Legacy refresh/termination/colour and view lists
# are intentionally preserved, not offered as new controls by this editor.
FIELDS = {
    "page_title": ("Page title", "Text in the browser tab.", "branding"),
    "header_text": ("Header text", "Optional short text beside the logo.", "branding"),
    "logo": (
        "Logo",
        "Upload an image or enter an existing file path on this server. One image is used in both appearances.",
        "branding",
    ),
    "icon_url": (
        "Logo link URL",
        "Optional HTTP(S) URL or path on this server. Leave blank for no link.",
        "branding",
    ),
    "favicon": (
        "Tab icon",
        "Upload an image or enter an existing file path on this server.",
        "branding",
    ),
    "export_image": (
        "Image export",
        "Offer export for image-capable views.",
        "controls",
    ),
    "export_table": ("Table export", "Offer export for tables.", "controls"),
    "show_history_controls": (
        "Snapshot controls",
        "Show snapshot navigation when applicable.",
        "controls",
    ),
    "show_freshness": (
        "Freshness indicator",
        "Show freshness in the shared status area.",
        "controls",
    ),
    "show_history_banner": (
        "History status",
        "Show historical context in the shared status area.",
        "controls",
    ),
    "show_statusline": ("Status line", "Show the lower status information.", "footer"),
    "show_help_note": ("Help note", "Show the view help note.", "footer"),
}
IMAGE_FIELDS = {"logo", "favicon"}
TEXT_FIELDS = {"page_title", "header_text", "icon_url"}


class Draft:
    def __init__(self, path: Path, *, name=None, assets_dir="plotsrv-assets"):
        requested = path.expanduser().absolute()
        self.path = requested.parent.resolve() / requested.name
        if not self.path.parent.is_dir() or self.path.is_symlink():
            raise SaveError("Choose a regular config file in an existing directory.")
        self.original = read_snapshot(self.path)
        self.document = _load_bounded(self.original.raw) if self.original.raw else {}
        self.name = name
        str(self.path).encode("utf-8")
        if name is not None:
            if not isinstance(name, str) or len(name) > 512:
                raise SaveError("Instance name is too long or invalid.")
            name.encode("utf-8")
        self.initial = settings.effective_section(
            self.document, "ui-settings", name=name, strict=True
        )
        # Do not resolve arbitrary configured asset paths or view thumbnails here.
        self.ui = load_ui_settings(
            section={
                k: v for k, v in self.initial.items()
                if k in FIELDS or k == "show_view_selector"
            },
            resolve_files=False,
        )
        self.values = {
            key: getattr(self.ui, key) for key in FIELDS if key not in IMAGE_FIELDS
        }
        self.values.update({key: self.initial.get(key, "") for key in IMAGE_FIELDS})
        for key, value in self.values.items():
            if key in IMAGE_FIELDS | TEXT_FIELDS and (
                not isinstance(value, str)
                or len(value) > 1024
                or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
            ):
                raise SaveError(
                    "An existing UI text/image setting is unsupported; repair it in YAML first."
                )
        self.initial_values = dict(self.values)
        self.images = Images(self.path.parent, assets_dir)
        self.edits = {}
        if self.original.raw is None:
            for key in FIELDS:
                self._edit(key)
        self.review = None
        self.review_id = None
        self.closed = False

    def state(self):
        return {
            "values": self.values,
            "fields": {
                k: {"label": v[0], "help": v[1], "region": v[2]}
                for k, v in FIELDS.items()
            },
            "path": str(self.path),
            "scope": self.name or "global",
            "assets_dir": str(self.images.root),
            "preserved": bool(self.initial.keys() - FIELDS.keys()),
        }

    def change(self, values):
        if type(values) is not dict or values.keys() - FIELDS.keys():
            raise SaveError("Unknown UI setting.")
        for key, value in values.items():
            if key in IMAGE_FIELDS:
                if type(value) is not str or len(value) > 512 or any(
                    ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value
                ):
                    raise SaveError("Use an image path of at most 512 printable characters.")
                if value and (
                    value != value.strip()
                    or value.startswith(("http:", "https:", "/static/", "/assets/"))
                    or not (self.path.parent / value).expanduser().is_file()
                ):
                    raise SaveError("Choose an existing image file on this server.")
            elif key in TEXT_FIELDS:
                if (
                    type(value) is not str
                    or len(value) > 512
                    or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
                ):
                    raise SaveError("Use at most 512 printable characters.")
                if key == "icon_url" and value and not _icon_link_url(value):
                    raise SaveError("Logo link must be an HTTP(S) URL or a path on this server.")
            elif type(value) is not bool:
                raise SaveError("Choose an on/off value.")
        self.values.update(values)
        parsed = load_ui_settings(
            section={k: v for k, v in self.values.items() if k in TEXT_FIELDS},
            resolve_files=False,
        )
        for key in TEXT_FIELDS & values.keys():
            self.values[key] = getattr(parsed, key)
        for key in values:
            if key in IMAGE_FIELDS:
                self.images.staged.pop(key, None)
            self._edit(key)
        self.review = self.review_id = None

    def _edit(self, key):
        path = scoped_path(self.document, ("ui-settings", key), self.name)
        if (
            self.original.raw is not None
            and self.values[key] == self.initial_values[key]
        ):
            self.edits.pop(path, None)
        else:
            self.edits[path] = self.values[key]

    def upload(self, key, raw, filename):
        if key not in IMAGE_FIELDS:
            raise SaveError("Choose a logo or tab icon.")
        self.values[key] = self.images.stage(key, raw, filename)
        self._edit(key)
        self.review = self.review_id = None

    def prepare(self):
        if read_snapshot(self.path) != self.original:
            raise SaveError(
                "Config changed since opening. Cancel and reopen to review the current file."
            )
        proposed = narrow_yaml(self.original.raw, self.edits)
        document = settings.parse_yaml_config(proposed)
        effective = settings.effective_section(
            document, "ui-settings", name=self.name, strict=True
        )
        parsed = load_ui_settings(
            section={k: v for k, v in effective.items() if k in FIELDS},
            resolve_files=False,
        )
        for key in FIELDS.keys() - IMAGE_FIELDS:
            if getattr(parsed, key) != self.values[key]:
                raise SaveError("Runtime UI settings disagree with the draft.")
        # Show only owned fields; never disclose unrelated configuration or source IDs.
        before = {k: v for k, v in self.initial.items() if k in FIELDS}
        after = {k: v for k, v in effective.items() if k in FIELDS}
        diff = "".join(
            difflib.unified_diff(
                yaml.safe_dump(before, sort_keys=False).splitlines(True),
                yaml.safe_dump(after, sort_keys=False).splitlines(True),
                fromfile="effective UI before",
                tofile="effective UI after",
            )
        )
        planned = {" / ".join(path): value for path, value in self.edits.items()}
        text = (
            "Scope: "
            + (self.name or "global")
            + "\nTarget: "
            + str(self.path)
            + "\nOnly the listed UI settings change. Other UI keys, comments, sections and instances are preserved.\n\nPlanned YAML paths:\n"
            + yaml.safe_dump(planned, sort_keys=False)
            + "\n"
            + (diff or "(no changes)\n")
        )
        self.review = Review(
            self.path, self.original, self.path, self.original, proposed, text
        )
        self.review_id = secrets.token_urlsafe(24)
        return {"review_id": self.review_id, "text": text}

    def finish(self, review_id):
        if not self.review or not secrets.compare_digest(
            str(review_id), self.review_id or ""
        ):
            raise SaveError("Review the current draft before saving.")
        # Assets are created with exclusive names before the config references them.
        # Failed config save rolls back only this transaction's newly created files.
        with self.images.finalise() as transaction:
            backup = save(self.review)
            transaction.commit = True
        self.closed = True
        self.images.clear()
        return {
            "path": str(self.path),
            "backup": str(backup) if backup else None,
            "message": "Saved. Use this config when starting plotsrv; running services were not restarted.",
        }

    def preview(self):
        from ..html import render_index
        from ..view_metadata import ViewMeta

        ui = load_ui_settings(
            section={k: v for k, v in self.values.items() if k not in IMAGE_FIELDS},
            resolve_files=False,
        )
        ui = replace(
            ui,
            show_view_selector=self.ui.show_view_selector,
            logo_url=DEFAULT_LOGO_URL,
            favicon_url=DEFAULT_FAVICON_URL,
            terminate_process_option=False,
            featured_views=(),
            compact_views=(),
        )
        return render_index(
            kind="table",
            table_view_mode="simple",
            table_html_simple="<table><thead><tr><th>Stage</th><th>Rows</th><th>Status</th></tr></thead><tbody><tr><td>Load</td><td>120</td><td>Complete</td></tr><tr><td>Validate</td><td>118</td><td>Complete</td></tr><tr><td>Export</td><td>118</td><td>Complete</td></tr></tbody></table>",
            max_table_rows_simple=3,
            max_table_rows_rich=3,
            ui_settings=ui,
            views=[
                ViewMeta(
                    view_id="example:table",
                    label="Example table",
                    section="Preview",
                    kind="table",
                    icon_key="table",
                )
            ],
            active_view_id="example:table",
            static_preview=True,
        )
