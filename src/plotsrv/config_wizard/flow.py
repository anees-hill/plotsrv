"""Sequential questions over the existing Draft, schema and atomic writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config
from ..connection_config import get_publisher_sources, get_server_connection_config
from ..discovery import scan_sources
from ..source_setup import watch_descriptor
from ..source_targets import default_source_target
from ..cli_parser import WatchSpec
from .draft import Draft, FIELDS, FieldSpec, _load_bounded
from .inputs import Prompts, format_size, parse_duration, parse_size
from .saving import DELETE, prepare, save
from .schema import PAGES, fields_for, review_projection


_KEEP = object()
_FRESHNESS_STARTER = {"expected_every": "60s", "warn_after": "2m", "overdue_after": "10m"}


def _current_role(draft: Draft) -> str:
    if draft.original is None:
        return "combined"
    publisher = "publisher-settings" in draft.config
    server = "server-settings" in draft.config or (
        publisher and any(key in draft.config for key in ("storage-settings", "freshness-settings")))
    if publisher and server:
        return "combined"
    if publisher:
        return "publisher"
    if server:
        return "server"
    return "combined"


def _display(spec, value: Any) -> str:
    if value is None:
        return "off" if spec.kind == "duration" else "unset"
    if spec.kind == "bool":
        return "yes" if value else "no"
    if spec.kind == "int" and spec.units == "bytes":
        return format_size(value)
    if spec.kind == "float" and spec.units == "MiB" and value != "off":
        return format_size(value, megabytes=True)
    return str(value)


def _parse_field(spec, text: str) -> Any:
    if spec.kind == "duration":
        value = parse_duration(text)
        return spec.parse("off" if value is None else value)
    if spec.kind == "int" and spec.units == "bytes":
        return spec.parse(str(parse_size(text)))
    if spec.kind == "float" and spec.units == "MiB":
        if spec.key == "watch_max_mb" and text.lower() in {"off", "none"}:
            return "off"
        return spec.parse(str(parse_size(text, megabytes=True)))
    if spec.kind == "env" and text.lower() in {"off", "none"}:
        return None
    return spec.parse(text)


def _field(draft: Draft, prompts: Prompts, key: str, *, spec=None,
           inherit: bool = False) -> None:
    spec = spec or FIELDS[key]
    value = draft.value(spec)
    overridden = bool(inherit and spec.path[-1] in draft.section(spec.path[0]).get(
        "views", {}).get(spec.path[2], {}))
    if spec.kind == "bool":
        if inherit:
            choice = prompts.choice(
                spec.label, [("inherit", "Inherit global setting"),
                             ("yes", "Yes"), ("no", "No")],
                default=("yes" if value else "no") if overridden else "inherit",
                help_text=spec.meaning + " Inherit removes this view's override.",
            )
            if choice == "inherit":
                draft.update_edits({spec.path: DELETE})
            elif not overridden or (choice == "yes") != value:
                draft.update_edits({spec.path: choice == "yes"})
            return
        changed = prompts.yes_no(spec.label, default=bool(value), help_text=spec.meaning)
        if changed != value:
            draft.update_edits({spec.path: changed})
        return
    if spec.kind == "duration":
        prompts.hint_once("duration", "Duration example: 30m, 4h or 2d. Enter ? for help.")
    if spec.units in {"bytes", "MiB"}:
        prompts.hint_once("size", "Size example: 500 KB, 10 MB or 1.5 GB (binary units). Enter ? for help.")
    help_text = spec.meaning + (" Enter inherit to remove this view's override." if inherit else "")
    if spec.kind == "duration":
        help_text += " Use s, m, h or d; off unsets the interval. This is a duration, not a clock time."
    if spec.units in {"bytes", "MiB"}:
        help_text += " KB/MB/GB use 1024-based units; raw bytes are accepted for byte fields."
    if spec.kind == "env" or (spec.kind == "url" and draft.role != "publisher"):
        help_text += " Enter off to remove the configured value."

    def parse(answer: str) -> Any:
        if inherit and answer.lower() == "inherit":
            return DELETE
        if spec.kind == "url" and answer.lower() in {"off", "none"}:
            if draft.role == "publisher":
                raise ValueError("A publisher needs a destination URL.")
            return None
        result = _parse_field(spec, answer)
        if key == "bind_host":
            get_server_connection_config(section={"bind": {
                "host": result, "port": draft.value(FIELDS["bind_port"]),
            }})
        return result

    answer = prompts.ask(spec.label, default=_KEEP, display=_display(spec, value),
                         parse=parse, help_text=help_text)
    if answer is not _KEEP and (answer is DELETE or not overridden or answer != value):
        draft.update_edits({spec.path: answer})


def _check_freshness(draft: Draft, prompts: Prompts, view_id: str | None = None) -> None:
    """Keep threshold ordering valid while the user is still in the section."""
    prefix = ("freshness-settings", "views", view_id) if view_id else ("freshness-settings",)
    while True:
        section = draft.section("freshness-settings")
        row = section.get("views", {}).get(view_id, {}) if view_id else {}
        effective = {**section, **row}
        warn = config._parse_duration_seconds(
            effective.get("warn_after") or effective.get("expected_every"))
        if view_id and "overdue_after" in row:
            overdue_value = row["overdue_after"]
        elif view_id and "error_after" in row:
            overdue_value = row["error_after"]
        else:
            overdue_value = section.get("overdue_after")
            if overdue_value is None:
                overdue_value = section.get("error_after")
        overdue = config._parse_duration_seconds(overdue_value)
        if not (warn and overdue and warn > overdue):
            return
        prompts.say("  Overdue must be later than the warning threshold.")
        base = FIELDS["freshness_overdue_after"]
        from dataclasses import replace
        spec = replace(base, path=(*prefix, "overdue_after"),
                       default=draft.value(base))
        _field(draft, prompts, spec.key, spec=spec, inherit=view_id is not None)


def _fields(draft: Draft, prompts: Prompts, keys: list[str]) -> None:
    for key in keys:
        _field(draft, prompts, key)


def _discover(draft: Draft, prompts: Prompts) -> list[str]:
    try:
        if draft.role == "server":
            publisher = draft.config.get("publisher-settings")
            discovery = publisher.get("discovery") if isinstance(publisher, dict) else None
            raw = draft.cli_target or (discovery.get("target") if isinstance(discovery, dict) else None)
            target = raw or default_source_target()
            from ..source_targets import resolve_source_target
            root = resolve_source_target(target, base=draft.path.parent if raw and not draft.cli_target else Path.cwd())
            include_pruned = False
        else:
            setup = draft.sources()
            root = setup.scan_root(default_source_target())
            include_pruned = setup.include_pruned
        result = scan_sources(root, include_pruned=include_pruned)
    except (ValueError, OSError, TypeError):
        prompts.say("No readable publisher source found; discovery skipped.")
        return []
    if draft.role == "server":
        draft.result = result
        draft.selected_ids = {view.descriptor().view_id for view in result.views}
    else:
        draft.accept_scan(result, (str(root), include_pruned))
    views = list(result.views)
    prompts.say(f"Found {len(views)} plotsrv view{'s' if len(views) != 1 else ''} in this project.")
    if result.issue_count:
        prompts.say(f"  {result.issue_count} declaration(s) could not be resolved; review discovery diagnostics before sealing a catalogue.")
    if not result.complete:
        prompts.say("  Scan was incomplete. View selection is unavailable for this scope.")
    if draft.role == "server" or not result.complete or not views:
        return sorted({view.descriptor().view_id for view in views})
    current = draft.selected_ids or set()
    all_ids = {view.descriptor().view_id for view in views}
    hidden = all_ids - current
    if hidden:
        prompts.say(f"  {len(hidden)} discovered view(s) are currently hidden.")
    change = prompts.yes_no(
        "Change visible views?" if draft.original else "Hide any discovered views?",
        default=False,
        help_text="Discovery finds source declarations without running code. Hidden views remain discovered, but the saved exact selection excludes them from the publisher catalogue.",
    )
    if change:
        for index, view in enumerate(views, 1):
            descriptor = view.descriptor()
            prompts.say(f"  {index}  {descriptor.label} ({descriptor.view_id})")
        selected = prompts.numbers(
            "Which views should be hidden? Enter numbers separated by commas",
            count=len(views),
            default=tuple(index for index, view in enumerate(views, 1)
                          if view.descriptor().view_id in hidden),
            help_text="Enter comma-separated row numbers. Press Enter to keep the current hidden set; type none to show all views.",
        )
        chosen = {views[index - 1].descriptor().view_id for index in selected}
        draft.selected_ids = all_ids - chosen
        draft.selection_changed = chosen != hidden
    return sorted(all_ids)


def _server(draft: Draft, prompts: Prompts) -> None:
    prompts.section("Server")
    host = draft.value(FIELDS["bind_host"])
    remote = host not in {"127.0.0.1", "localhost", "::1"}
    expose = prompts.yes_no(
        "Allow connections from other machines?", default=remote,
        help_text="Loopback keeps the dashboard on this machine. A network bind also exposes dashboard reads; protect reads at your proxy. Remote publishers need a key or explicit anonymous-ingestion opt-in.",
    )
    if expose != remote:
        draft.update_edits({FIELDS["bind_host"].path: "0.0.0.0" if expose else "127.0.0.1"})
    if expose:
        _field(draft, prompts, "bind_host")
        _field(draft, prompts, "ingress_key")
        if not draft.value(FIELDS["ingress_key"]):
            _field(draft, prompts, "allow_remote")
            if not draft.value(FIELDS["allow_remote"]):
                prompts.say("  A non-loopback server needs a publisher key or explicit anonymous-ingestion opt-in.")
                while not draft.value(FIELDS["ingress_key"]) and not draft.value(FIELDS["allow_remote"]):
                    _field(draft, prompts, "ingress_key")
                    if not draft.value(FIELDS["ingress_key"]):
                        _field(draft, prompts, "allow_remote")
    if draft.original is None or expose != remote:
        _field(draft, prompts, "bind_port")
    if draft.original is None:
        for key in ("bind_host", "bind_port"):
            spec = FIELDS[key]
            draft.edits.setdefault(spec.path, draft.value(spec))


def _publisher(draft: Draft, prompts: Prompts) -> None:
    if draft.role != "publisher":
        return
    prompts.section("Publisher")
    prompts.say("This process sends views to an existing plotsrv server.")
    spec = FIELDS["destination"]
    while not draft.value(spec):
        value = prompts.ask("Destination URL", required=True,
                            parse=spec.parse, help_text=spec.meaning)
        draft.update_edits({spec.path: value})
    if draft.original is not None:
        _field(draft, prompts, "destination")
    _field(draft, prompts, "bearer")


def _per_view(draft: Draft, prompts: Prompts, page: str, ids: list[str]) -> None:
    if not ids:
        return
    if not prompts.yes_no("Customise individual views?", default=False,
                          help_text="Only selected views receive overrides. Other views inherit the global settings."):
        return
    while True:
        for index, view_id in enumerate(ids, 1):
            prompts.say(f"  {index}  {view_id}")
        selected = prompts.numbers("Choose views to customise", count=len(ids),
                                   help_text="Enter one or more row numbers, separated by commas.")
        if not selected:
            break
        for number in selected:
            view_id = ids[number - 1]
            prompts.say(f"  {view_id} (Enter keeps each inherited or current value; type inherit to remove an override)")
            for spec in fields_for(page, draft, view_id):
                if spec.key == "storage_watch_enabled":
                    continue  # Asked with watched files instead.
                _field(draft, prompts, spec.key, spec=spec, inherit=True)
            if page == "freshness":
                _check_freshness(draft, prompts, view_id)
            if draft.section(f"{page}-settings").get("views", {}).get(view_id) == {}:
                draft.update_edits({(f"{page}-settings", "views", view_id): DELETE})
        if not prompts.yes_no("Customise another view?", default=False,
                              help_text="Choose more discovered or previously configured logical view IDs."):
            break


def _capability(draft: Draft, prompts: Prompts, page: str, ids: list[str]) -> None:
    key = f"{page}_enabled"
    title = "Storage" if page == "storage" else "Freshness"
    prompts.section(title)
    current = bool(draft.value(FIELDS[key]))
    if draft.original is None:
        enabled = prompts.yes_no(
            "Enable storage?" if page == "storage" else "Enable freshness monitoring?",
            default=True,
            help_text=(
                "Storage saves latest values and optional snapshots on the server's disk so views can survive restarts. Disabling it leaves live views in memory."
                if page == "storage" else
                "Freshness compares the time since the server last received each view against expected and warning intervals. It does not inspect event timestamps."
            ),
        )
    else:
        count = len(draft.section(f"{page}-settings").get("views", {}))
        prompts.say(f"  {'Enabled' if current else 'Disabled'}; {count} view override(s).")
        if not prompts.yes_no(f"Change {page} settings?", default=False,
                              help_text="Press Enter to preserve the entire existing section, including advanced and per-view values."):
            return
        enabled = prompts.yes_no(f"Enable {page}?", default=current,
                                 help_text=FIELDS[key].meaning)
    if enabled != current:
        draft.update_edits({FIELDS[key].path: enabled})
    if not enabled:
        return
    if page == "freshness" and not any(draft.value(FIELDS["freshness_" + part])
                                       for part in _FRESHNESS_STARTER):
        for part, value in _FRESHNESS_STARTER.items():
            draft.edits.setdefault(FIELDS["freshness_" + part].path, value)
    if not prompts.yes_no(f"Customise {page}?", default=False,
                          help_text=f"The existing {page} defaults are ready to use. Customisation changes global values or individual view exceptions."):
        return
    normal = (["storage_root_dir", "storage_max_snapshot_size_mb",
               "storage_default_keep_last", "storage_default_min_store_interval"]
              if page == "storage" else
              ["freshness_expected_every", "freshness_warn_after", "freshness_overdue_after"])
    _fields(draft, prompts, normal)
    if page == "freshness":
        _check_freshness(draft, prompts)
    _per_view(draft, prompts, page, ids)
    if page == "storage" and prompts.yes_no(
        "Configure advanced storage settings?", default=False,
        help_text="Latest-view restore and bounded storage writer queues. Existing values remain unchanged when skipped.",
    ):
        _fields(draft, prompts, PAGES["storage_advanced"])


def _limits(draft: Draft, prompts: Prompts, ids: list[str]) -> None:
    prompts.section("Limits")
    if not prompts.yes_no("Customise safety limits?", default=False,
                          help_text="Limits cap prepared objects and watched-file reads. Existing limits already allow ordinary large files; change them only for a specific workload."):
        return
    _fields(draft, prompts, ["limit_max_plot_bytes", "limit_max_artifact_text_chars", "watch_max_mb"])
    if prompts.yes_no("Configure other limits?", default=False,
                      help_text="Table row/column and JSON item bounds. Skipped values keep their current defaults."):
        _fields(draft, prompts, [key for key in PAGES["limits"] if key not in
                               {"limit_max_plot_bytes", "limit_max_artifact_text_chars", "watch_max_mb"}])
    if ids and prompts.yes_no("Customise truncation for individual views?", default=False,
                              help_text="Only selected views get text, HTML or Markdown display limits; other views inherit the global policy."):
        for index, view_id in enumerate(ids, 1):
            prompts.say(f"  {index}  {view_id}")
        selected = prompts.numbers("Choose views", count=len(ids),
                                   help_text="Enter one or more row numbers, separated by commas.")
        for number in selected:
            view_id = ids[number - 1]
            prompts.say(f"  {view_id} (Enter keeps the current value; type inherit to remove an override)")
            for kind in ("text", "html", "markdown"):
                default = draft.section("limits").get("truncate_after", {}).get(
                    kind, config._DEFAULTS["limits"]["truncate_after"].get(kind))
                spec = FieldSpec(
                    f"truncate_{kind}", ("limits", "views", view_id, "truncate_after", kind),
                    f"{kind.capitalize()} character limit", "keep", default,
                    "Display truncation after a view is prepared; off allows the whole value.",
                    "characters", per_view=True,
                )
                _field(draft, prompts, spec.key, spec=spec, inherit=True)


def _watch_identity(row: dict) -> str:
    return watch_descriptor(WatchSpec(**row)).view_id


def _watch_path(draft: Draft, path: str) -> Path:
    candidate = Path(path).expanduser()
    return (candidate if candidate.is_absolute() else draft.path.parent / candidate).resolve()


def _watches(draft: Draft, prompts: Prompts, *, storage_enabled: bool) -> None:
    if draft.role == "server":
        return
    prompts.section("Watched files")
    rows = draft.watch_entries()
    if rows:
        prompts.say(f"  {len(rows)} watched file(s) configured.")
        for index, row in enumerate(rows, 1):
            prompts.say(f"  {index}  {row.get('label') or Path(row['path']).stem}  {row['path']}")
        if not prompts.yes_no("Change watched files?", default=False,
                              help_text="Existing entries stay untouched unless you choose to edit, remove, or add one."):
            return
    asked_storage_default = False
    while True:
        if rows:
            options = [(str(index), f"Edit {row.get('label') or Path(row['path']).stem}")
                       for index, row in enumerate(rows, 1)]
            options.append(("add", "Add a watched file"))
            action = prompts.choice("Choose an action", options, default="add",
                                    help_text="Select a row to edit or choose Add. Existing files are not changed until final confirmation.")
            index = int(action) - 1 if action != "add" else -1
        else:
            if not prompts.yes_no("Add a watched file?", default=False,
                                  help_text="Watch a local file and publish its latest content as a view. Paths are resolved beside this config file."):
                break
            index = -1
        existing = rows[index].copy() if index >= 0 else {}
        if index >= 0 and prompts.yes_no("Remove this watched file?", default=False,
                                         help_text="This removes only its config entry, not the file on disk."):
            rows.pop(index)
            draft.watch_rows = rows.copy()
        else:
            while True:
                raw = prompts.ask("File path", default=existing.get("path"),
                                  display=existing.get("path"), required=True,
                                  help_text="A local file path, relative to the config folder or absolute. A missing file may be watched once its parent exists.")
                assert isinstance(raw, str)
                full = _watch_path(draft, raw)
                if full.exists() and not full.is_file():
                    prompts.say("  Choose a regular file, not a directory.")
                    continue
                if not full.exists():
                    if not full.parent.is_dir():
                        prompts.say("  Parent directory does not exist.")
                        continue
                    if not prompts.yes_no("File does not exist yet. Watch when created?", default=False,
                                          help_text="plotsrv will keep checking this path and show the file once it appears."):
                        continue
                duplicate = next((n for n, row in enumerate(rows)
                                  if n != index and _watch_path(draft, row["path"]) == full), None)
                if duplicate is not None:
                    prompts.say(f"  Already watched as {rows[duplicate].get('label') or Path(rows[duplicate]['path']).stem}.")
                    if prompts.yes_no("Edit that entry instead?", default=True,
                                      help_text="A path should have one watch entry. Editing preserves its position and stable ID."):
                        index = duplicate
                        existing = rows[index].copy()
                        raw = existing["path"]
                        break
                    continue
                break
            label_default = existing.get("label") or Path(raw).stem or Path(raw).name
            label = prompts.ask("Label", default=label_default, display=label_default,
                                required=True, help_text="The human-readable view name; defaults to the filename without its suffix.")
            row = {**existing, "path": raw, "label": label}
            if prompts.yes_no("Customise this watched file?", default=False,
                              help_text="Optional section, read direction, storage representation and stable logical ID. The normal defaults work for most files."):
                section = prompts.ask("Section", default=row.get("section") or "watch",
                                      display=row.get("section") or "watch",
                                      help_text="The view group shown in the dashboard.")
                row["section"] = section
                mode = prompts.choice("Read mode", [("auto", "Automatic"), ("head", "Start of file"),
                                                     ("tail", "End of file")],
                                      default=row.get("read_mode") or "auto",
                                      help_text="Tail suits growing logs; head suits files whose useful content is at the start. Automatic uses the runtime default.")
                if mode == "auto":
                    row.pop("read_mode", None)
                else:
                    row["read_mode"] = mode
                material = prompts.choice("Representation", [("auto", "Automatic"), ("memory", "Memory"),
                                                              ("file", "File-backed")],
                                          default=row.get("materialization") or "auto",
                                          help_text="Automatic selects memory or bounded file-backed previews according to file size.")
                if material == "auto":
                    row.pop("materialization", None)
                else:
                    row["materialization"] = material
                if row.get("view_id"):
                    stable = prompts.ask("Stable view ID", default=row["view_id"],
                                         display=row["view_id"], help_text="Preserves this machine identity even if the display label changes.")
                    row["view_id"] = stable
            try:
                view_id = _watch_identity(row)
                other_ids = {_watch_identity(item) for n, item in enumerate(rows) if n != index}
                if view_id in other_ids:
                    raise ValueError("Another watched file already uses that view identity.")
                candidate = rows.copy()
                if index < 0:
                    candidate.append(row)
                else:
                    candidate[index] = row
                get_publisher_sources(section={"watch": candidate}, base=draft.path.parent)
            except ValueError as error:
                prompts.say(f"  {error} Entry was not changed; choose it again to correct it.")
            else:
                rows = candidate
                draft.watch_rows = rows.copy()
                if storage_enabled:
                    if not asked_storage_default:
                        _field(draft, prompts, "storage_watch_enabled")
                        asked_storage_default = True
                    _watch_storage(draft, prompts, view_id)
        if not prompts.yes_no("Change another watched file?", default=False,
                              help_text="Add, edit or remove another watched file."):
            break


def _watch_storage(draft: Draft, prompts: Prompts, view_id: str) -> None:
    if not prompts.yes_no("Customise storage for this watched file?", default=False,
                          help_text="Watched-file snapshots are off by default. A per-view override can enable them without changing other watches."):
        return
    base = FIELDS["storage_watch_enabled"]
    from dataclasses import replace
    spec = replace(base, path=("storage-settings", "views", view_id, "watch_enabled"),
                   default=draft.value(base))
    _field(draft, prompts, spec.key, spec=spec, inherit=True)


def _advanced(draft: Draft, prompts: Prompts) -> None:
    prompts.section("Advanced")
    if not prompts.yes_no("Configure advanced options?", default=False,
                          help_text="Publisher budgets, server security, checks and watch loading controls remain at their current values unless selected."):
        return
    if draft.role == "combined" and prompts.yes_no(
        "Configure a remote publisher destination?", default=False,
        help_text="Combined mode normally publishes to its local server. A destination URL routes publisher operations to a separate receiving server.",
    ):
        _field(draft, prompts, "destination")
        if draft.value(FIELDS["destination"]):
            _field(draft, prompts, "bearer")
    groups = []
    if draft.role != "server":
        groups += [("publish", "Publisher and stream budgets")]
    if draft.role != "publisher":
        groups += [("server", "Server admission"), ("security", "Server security"),
                   ("checks", "Checks and webhooks")]
    if draft.role != "publisher":
        groups += [("watch", "File-backed watch loading")]
    if draft.role != "server":
        groups += [("publisher", "Observation admission")]
    for key, label in groups:
        if prompts.yes_no(f"Configure {label.lower()}?", default=False,
                          help_text="Every setting in this group keeps its current value when you press Enter."):
            specs = fields_for(key, draft)
            if key == "server":
                specs = [spec for spec in specs if spec.key == "admission"]
            if key == "publisher" and not draft.value(FIELDS["destination"]):
                specs = [spec for spec in specs if spec.key != "request_timeout"]
            for spec in specs:
                _field(draft, prompts, spec.key, spec=spec)
            if key == "server" and draft.value(FIELDS["admission"]) == "catalogue-locked":
                prompts.say("  Locked admission accepts only configured IDs or an explicitly sealed publisher catalogue.")
                while prompts.yes_no("Add an allowed logical view ID?", default=False,
                                     help_text="Add reviewed IDs from every producer. An empty list admits none until explicit bootstrap."):
                    value = prompts.ask("View ID", required=True,
                                        help_text="A stable logical ID such as reports:daily.")
                    try:
                        draft.add_id(value, owner="server")
                    except ValueError as error:
                        prompts.say(f"  {error}")


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result.update(_flatten(item, (*prefix, str(key))))
        return result
    if prefix == ("publisher-settings", "watch") and isinstance(value, list):
        result = {}
        for index, row in enumerate(value, 1):
            identity = _watch_identity(row) if isinstance(row, dict) else str(index)
            result.update(_flatten(row, (*prefix, identity)))
        return result
    return {prefix: value}


def _review(draft: Draft, prompts: Prompts):
    review = prepare(draft, str(draft.path))
    if draft.original is not None and review.proposed == draft.original:
        prompts.say("\nNo changes. The configuration was not rewritten.")
        return None
    before = review_projection(draft.config, draft.name, draft.role)
    after = review_projection(_load_bounded(review.proposed), draft.name, draft.role)
    old, new = _flatten(before), _flatten(after)
    prompts.section("Review" if draft.original is None else "Changes")
    if draft.original is None:
        prompts.say(f"  New {draft.role} configuration at {draft.path}")
    changes = [(path, old.get(path), new.get(path)) for path in sorted(old.keys() | new.keys())
               if old.get(path) != new.get(path)]
    for path, before_value, after_value in changes[:24]:
        label = ".".join(path)
        if len(label) > 72:
            label = "…" + label[-71:]
        if before_value is None:
            prompts.say(f"  + {label}: {after_value}")
        elif after_value is None:
            prompts.say(f"  - {label}")
        else:
            prompts.say(f"  {label}: {before_value} -> {after_value}")
    if len(changes) > 24:
        prompts.say(f"  … and {len(changes) - 24} more changes.")
    if draft.original is not None:
        prompts.say("  Everything else is unchanged.")
    if not prompts.yes_no("Write this configuration?", default=False,
                          help_text="Writes atomically after checking the file has not changed. Existing files receive a backup. Answer no to leave the file untouched."):
        prompts.say("Not saved. No files changed.")
        return None
    backup = save(review)
    prompts.say(f"Saved {review.path}")
    if backup:
        prompts.say(f"Backup: {backup}")
    return review.path


def run(draft: Draft, prompts: Prompts) -> Path | None:
    prompts.say("plotsrv configuration")
    if draft.original is not None:
        prompts.say(f"Found {draft.path}. Press Enter to keep current values.")
    prompts.say("Tip: enter ? at any prompt for help.")
    draft.role = prompts.choice(
        "How will this installation be used?",
        [("publisher", "Publisher — send views to another server"),
         ("server", "Server — receive and display views"),
         ("combined", "Publisher + server on this machine")],
        default=_current_role(draft),
        help_text="A publisher reads local source/watched files and sends data. A server receives and displays it. Combined mode does both in one process.",
    )
    ids = _discover(draft, prompts)
    _publisher(draft, prompts)
    ids = sorted(set(ids) | set(draft.known_ids()))
    if draft.role != "publisher":
        _server(draft, prompts)
        _capability(draft, prompts, "storage", ids)
        _capability(draft, prompts, "freshness", ids)
    _limits(draft, prompts, ids)
    _watches(draft, prompts, storage_enabled=(
        draft.role != "publisher" and bool(draft.value(FIELDS["storage_enabled"]))))
    _advanced(draft, prompts)
    return _review(draft, prompts)
