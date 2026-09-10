"""Keyboard-only role/source foundation. Deliberately no save/finish operation."""

from __future__ import annotations

from itertools import groupby
import ipaddress
from urllib.parse import urlsplit

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, OptionList, Select, SelectionList, Static
from textual.widgets.selection_list import Selection

from .draft import Draft, FIELDS
from .scanning import ScanJob

ROLES = (
    ("combined", "Everything on this machine"),
    ("publisher", "Send data to another plotsrv server"),
    ("server", "Host a plotsrv server"),
)


class Roles(OptionList):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


class Views(SelectionList[str]):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("enter", "next_page", show=False),
        Binding("a", "all_views", show=False),
        Binding("c", "clear_views", show=False),
        Binding("r", "anchor", show=False),
        Binding("e", "range_end", show=False),
    ]

    def __init__(self, draft):
        self.anchor = None
        self.valid_values = set()
        options = []
        unique = (
            {v.descriptor().view_id: v.descriptor() for v in draft.result.views}
            if draft.result
            else {}
        )
        ordered = sorted(
            unique.values(), key=lambda d: (d.section or "default", d.view_id)
        )
        for section, views in groupby(ordered, key=lambda d: d.section or "default"):
            options.append(
                Selection(
                    Text(f"── {section} ──", style="bold"),
                    object(),
                    disabled=True,
                )
            )
            for view in views:
                self.valid_values.add(view.view_id)
                options.append(
                    Selection(
                        Text(f"{view.label}  ·  {view.view_id}"),
                        view.view_id,
                        view.view_id in (draft.selected_ids or ()),
                    )
                )
        super().__init__(*options, id="views")

    def action_next_page(self):
        self.app.action_next()

    def action_all_views(self):
        with self.prevent(self.SelectedChanged):
            for value in self.valid_values:
                self.select(value)
        self.post_message(self.SelectedChanged(self))

    def action_clear_views(self):
        self.deselect_all()

    def action_anchor(self):
        self.anchor = self.highlighted
        if self.anchor is not None:
            option = self.get_option_at_index(self.anchor)
            self.screen.query_one("#range", Static).update(
                Text(
                    f"Range anchor: {option.prompt}. Move to the end and press e to select."
                )
            )
            self.screen.update_help()

    def action_range_end(self):
        if self.anchor is not None and self.highlighted is not None:
            with self.prevent(self.SelectedChanged):
                for index in range(
                    min(self.anchor, self.highlighted),
                    max(self.anchor, self.highlighted) + 1,
                ):
                    option = self.get_option_at_index(index)
                    if not option.disabled:
                        self.select(option.value)
            self.post_message(self.SelectedChanged(self))
            self.anchor = None
            self.screen.query_one("#range", Static).update(
                "Range selected. r sets a new anchor; e selects through the end."
            )
            self.screen.update_help()


class Confirm(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Keep editing")]

    def compose(self):
        with Vertical(id="dialog"):
            yield Static("Abandon this draft? Nothing has been written.")
            yield Button("Keep editing", id="keep", variant="primary")
            yield Button("Abandon draft", id="abandon")

    def on_mount(self):
        self.query_one("#keep").focus()

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "abandon")


class Help(ModalScreen):
    BINDINGS = [
        ("escape", "dismiss", "Close help"),
        ("question_mark", "dismiss", "Close help"),
    ]

    def compose(self):
        with VerticalScroll(id="dialog"):
            yield Static("Keyboard help", classes="heading")
            yield Static(
                "Tab / Shift+Tab: move between fields and actions.\nArrows or j/k: move in lists. Space: toggle a view.\nEnter: choose a role or continue from the view list.\na: select all; c: clear all (in the view list).\nr: set range anchor; e: select through the highlighted end.\nEsc: dismiss/back. Left/Backspace: back outside text inputs.\nCtrl+C / Ctrl+Q: confirm abandonment. q is ordinary text.\n?: this help outside text fields; F1 works while editing.\n\nAll changes remain in memory. No endpoint is contacted and no catalogue is sealed. Discovery reads bounded Python source without importing your application. Cancellation is cooperative; an individual file/AST operation cannot be interrupted mid-call."
            )
            yield Button("Close help", id="close-help")

    def on_button_pressed(self, event):
        self.dismiss()


class Page(Screen):
    def __init__(self, stage):
        super().__init__()
        self.stage = stage

    def compose(self) -> ComposeResult:
        draft = self.app.draft
        yield Static(
            f"plotsrv configuration · {self.stage.title()} · unsaved", id="title"
        )
        with VerticalScroll(id="content"):
            if self.stage == "role":
                yield Static("What would you like to set up?", classes="heading")
                yield Roles(*(title for _, title in ROLES), id="roles")
            elif self.stage == "sources":
                yield Static(
                    "Files and application code stay on this machine. A package/path can focus discovery; leaving it empty uses normal project detection."
                )
                for key in ("destination", "bearer", "target"):
                    spec = FIELDS[key]
                    value = (
                        draft.cli_target
                        if key == "target" and draft.cli_target
                        else draft.value(spec)
                    )
                    yield Static(spec.label, id=f"label-{key}")
                    yield Input(
                        self.app.source_inputs.get(
                            key, str(value) if value is not None else ""
                        ),
                        id=key,
                        max_length=4096,
                    )
                if draft.original is not None:
                    selection = draft.sources().selection
                    yield Static(
                        Text(
                            f"Editing existing configuration. Discovery selection starts from: {selection or 'all (runtime default)'}. Existing selections are not reset when returning to this page."
                        )
                    )
                yield Static(
                    "Watched files (optional; config-relative paths)", classes="heading"
                )
                yield Static(self.watch_summary(), id="watch-summary", markup=False)
                yield Input(
                    placeholder="Local file path", id="watch-path", max_length=4096
                )
                yield Input(
                    placeholder="Stable logical view ID, e.g. logs:service",
                    id="watch-id",
                    max_length=512,
                )
                yield Select(
                    [("Automatic head/tail", ""), ("Head", "head"), ("Tail", "tail")],
                    value="",
                    allow_blank=False,
                    id="watch-mode",
                )
                yield Button("Add watch to draft", id="add-watch")
                yield Button("Remove last watch", id="remove-watch")
                yield Button("Continue without discovery", id="skip")
            elif self.stage == "scanning":
                yield Static("Enumerating source files…", id="progress")
                yield Button("Cancel discovery / Back", id="cancel-scan")
            elif self.stage == "selection":
                yield Static(
                    "Choose discovered views. Logical IDs are preserved exactly."
                )
                yield Views(draft)
                yield Static(
                    "r: set range anchor; e: select through the highlighted end.",
                    id="range",
                )
                yield Static(
                    Text("\n".join(draft.diagnostics()) or "No discovery issues."),
                    id="diagnostics",
                )
            else:
                yield Static(Text(draft.preview()), id="preview")
            yield Static("", id="error", markup=False)
            with Horizontal(id="actions"):
                if self.stage != "role":
                    yield Button("Back", id="back")
                if self.stage != "scanning":
                    yield Button(
                        "Close draft" if self.stage == "preview" else "Next",
                        id="next",
                        variant="primary",
                    )
        with VerticalScroll(id="help-panel"):
            yield Static("", id="context-help", markup=False)
        yield Static("", id="legend", markup=False)

    def watch_summary(self):
        watches = self.app.draft.sources().watches
        return (
            "\n".join(
                f"{w.view_id or '(derived ID)'} ← {w.path} ({w.read_mode or 'automatic'})"
                for w in watches
            )
            or "No watched files configured."
        )

    def on_mount(self):
        if self.stage == "role":
            roles = self.query_one(Roles)
            roles.highlighted = next(
                i for i, (key, _) in enumerate(ROLES) if key == self.app.draft.role
            )
            roles.focus()
        elif self.stage == "sources":
            self.query_one("#destination", Input).focus()
            for key in ("destination", "bearer", "target"):
                self.mark_field(key)
        elif self.stage == "selection":
            self.query_one(Views).focus()
        else:
            self.query_one(Button).focus()
        self.update_help()

    def mark_field(self, key):
        spec = FIELDS[key]
        try:
            changed = spec.parse(self.query_one(f"#{key}", Input).value) != spec.default
        except ValueError:
            changed = True
        label = self.query_one(f"#label-{key}", Static)
        label.update(spec.label + (" *" if changed else ""))
        label.set_class(changed, "modified")

    def on_resize(self, event: events.Resize):
        self.query_one("#help-panel").styles.height = 3 if event.size.height < 24 else 6

    def update_help(self):
        focus = self.focused
        key = focus.id if focus else None
        if key in FIELDS:
            spec = FIELDS[key]
            help_text = spec.help(self.app.draft.origin(spec))
        elif key and key.startswith("watch-"):
            help_text = "Watch files are read only on the publishing machine, under existing watch bounds. Default: no watches; automatic head/tail follows file type. Use a stable logical ID, never a server-side filesystem identity. No file is opened by this stage."
        elif self.stage == "role":
            help_text = "Everything: local server and sources. Send data: publisher beside your files/code. Host: server only, with no source scan. Default: everything on this machine. Roles guide pages; all use the same config schema."
        else:
            help_text = "Draft only: Back keeps your choices in memory. Closing abandons them without changing files. Settings, per-view overrides, review/diff and saving follow in the settings stage."
        self.query_one("#context-help", Static).update(help_text)
        if isinstance(focus, Input):
            legend = "Tab / Shift+Tab fields · Enter next field · Esc back · F1 help · Ctrl+C/Q abandon"
        elif isinstance(focus, Views):
            anchor = " (set)" if focus.anchor is not None else ""
            legend = f"↑↓ / j k move · Space toggle · a all / c clear · r anchor{anchor} / e end · Enter next · Esc back · ? help · Ctrl+C/Q abandon"
        else:
            legend = "↑↓ / j k lists · Tab / Shift+Tab fields · Enter choose · Esc back · ? help · Ctrl+C/Q abandon"
        self.query_one("#legend", Static).update(legend)

    def on_descendant_focus(self, event):
        self.update_help()

    def on_screen_resume(self):
        if self.stage == "scanning" and self.app.job and self.app.job.done.is_set():
            self.call_after_refresh(self.app.poll_scan)

    def on_input_changed(self, event):
        if event.input.id in FIELDS:
            self.app.source_inputs[event.input.id] = event.value
            self.mark_field(event.input.id)

    def on_input_submitted(self, event):
        self.focus_next()

    def on_option_list_option_selected(self, event):
        if isinstance(event.option_list, Roles):
            self.app.action_next()

    def on_selection_list_selected_changed(self, event):
        if isinstance(event.selection_list, Views):
            self.app.draft.selected_ids = (
                set(event.selection_list.selected) & event.selection_list.valid_values
            )

    def on_button_pressed(self, event):
        action = event.button.id
        if action in ("back", "cancel-scan"):
            self.app.action_back()
        elif action == "next":
            self.app.action_next()
        elif action == "skip":
            if self.app.capture_sources():
                self.app.draft.result = None
                self.app.draft.selected_ids = None
                self.app.draft.scan_key = None
                self.app.draft.discovery_skipped = True
                self.app.show_stage("preview")
        elif action in ("add-watch", "remove-watch"):
            draft = self.app.draft
            try:
                if action == "add-watch":
                    draft.add_watch(
                        self.query_one("#watch-path", Input).value.strip(),
                        self.query_one("#watch-id", Input).value.strip(),
                        self.query_one("#watch-mode", Select).value,
                    )
                    self.query_one("#watch-path", Input).value = ""
                    self.query_one("#watch-id", Input).value = ""
                else:
                    draft.watch_rows = list(
                        draft.watch_rows
                        if draft.watch_rows is not None
                        else draft.section("publisher-settings").get("watch", [])
                    )[:-1]
                self.query_one("#watch-summary", Static).update(self.watch_summary())
                self.query_one("#error", Static).update("")
            except ValueError:
                self.query_one("#error", Static).update(
                    "Watch needs a bounded local path and unique logical ID. Check the configured watch entries."
                )


class ConfigWizard(App):
    TITLE = "plotsrv configuration"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c,ctrl+q", "abandon", "Abandon", priority=True),
        Binding("escape", "back", "Back"),
        Binding("left,backspace", "back", "Back", show=False),
        Binding("question_mark,f1", "help", "Help"),
    ]
    CSS = """
    Screen { background: $surface; }
    #title { height: auto; padding: 0 1; background: $primary-background; text-style: bold; }
    #content { height: 1fr; padding: 0 1; }
    .heading { text-style: bold; margin-top: 1; }
    #roles { height: 6; }
    #views { height: 14; min-height: 5; }
    #help-panel { height: 6; max-height: 35%; padding: 0 1; background: $boost; }
    #context-help { height: auto; }
    #legend { height: auto; padding: 0 1; background: $primary-background; }
    #actions { height: auto; }
    Button { margin: 0 1 0 0; }
    #error { color: $error; height: auto; }
    .modified { color: $text-muted; }
    Confirm, Help { align: center middle; background: $background 70%; }
    #dialog { width: 80%; max-width: 78; height: auto; max-height: 90%; padding: 1 2; border: round $primary; background: $surface; }
    """

    def __init__(self, draft: Draft):
        super().__init__()
        self.draft = draft
        self.job = None
        self.poll_timer = None
        self.pending_key = None
        self.stage = "role"
        self.source_inputs = {}

    def on_mount(self):
        self.push_screen(Page("role"))

    def show_stage(self, stage):
        self.stage = stage
        self.switch_screen(Page(stage))

    def check_action(self, action, parameters):
        if action == "back" and isinstance(self.focused, Input):
            # Esc still backs out via on_key; text-editing keys stay with Input.
            return False
        if action == "help" and isinstance(self.focused, Input):
            return False
        return True

    def on_key(self, event: events.Key):
        if isinstance(self.focused, Input) and event.key in ("escape", "f1"):
            event.prevent_default()
            event.stop()
            self.action_back() if event.key == "escape" else self.action_help()

    def action_help(self):
        if isinstance(self.screen, Page):
            self.push_screen(Help())

    def action_abandon(self):
        if isinstance(self.screen, Confirm):
            return
        self.push_screen(Confirm(), self.confirm_abandon)

    def confirm_abandon(self, abandon):
        if abandon:
            if self.job:
                self.job.cancel()
            self.exit()

    def action_back(self):
        if not isinstance(self.screen, Page):
            self.screen.dismiss()
            return
        if self.stage == "role":
            self.action_abandon()
            return
        if self.stage == "scanning" and self.job:
            self.job.cancel()
        if self.stage == "sources":
            self.capture_sources(strict=False)
        previous = {
            "sources": "role",
            "scanning": "sources",
            "selection": "sources",
            "preview": (
                "role"
                if self.draft.role == "server"
                else ("selection" if self.draft.result else "sources")
            ),
        }
        self.show_stage(previous[self.stage])

    def capture_sources(self, *, strict=True):
        values = {}
        try:
            for key in ("destination", "bearer", "target"):
                text = self.screen.query_one(f"#{key}", Input).value
                values[key] = FIELDS[key].parse(text)
            if strict and self.draft.role == "publisher" and not values["destination"]:
                raise ValueError(
                    "A destination URL is required to send data to another server."
                )
            if strict and values["bearer"]:
                if not values["destination"]:
                    raise ValueError(
                        "Set a destination for the bearer environment-variable reference."
                    )
                url = urlsplit(values["destination"])
                try:
                    loopback = ipaddress.ip_address(url.hostname).is_loopback
                except ValueError:
                    loopback = url.hostname == "localhost"
                if url.scheme != "https" and not loopback:
                    raise ValueError(
                        "Bearer publication requires HTTPS outside loopback."
                    )
            for key, value in values.items():
                self.draft.edits[FIELDS[key].path] = value
            # The edited value now supersedes the initial CLI target in the draft.
            if self.draft.cli_target is not None:
                self.draft.cli_target = values["target"]
            return True
        except ValueError as error:
            if strict:
                self.screen.query_one("#error", Static).update(str(error))
            return False

    def action_next(self):
        if not isinstance(self.screen, Page):
            return
        try:
            if self.stage == "role":
                self.draft.role = ROLES[self.screen.query_one(Roles).highlighted or 0][
                    0
                ]
                # Validate source configuration only for roles that use sources.
                if self.draft.role != "server":
                    self.draft.sources()
                    for key in ("destination", "bearer", "target"):
                        self.draft.value(FIELDS[key])
                else:
                    self.draft.preview()
                self.show_stage("preview" if self.draft.role == "server" else "sources")
            elif self.stage == "sources" and self.capture_sources():
                setup = self.draft.sources()
                key = (setup.target, setup.target_base, setup.include_pruned)
                if (
                    self.draft.result is not None
                    and self.draft.scan_key == key
                    and self.draft.result.complete
                ):
                    self.show_stage("selection")
                elif self.job and not self.job.done.is_set():
                    self.screen.query_one("#error", Static).update(
                        "Previous scan is still stopping. Please wait; another worker will not be started."
                    )
                else:
                    self.pending_key = key
                    if key != self.draft.scan_key:
                        self.draft.result = None
                        self.draft.selected_ids = None
                    self.job = ScanJob(setup)
                    self.show_stage("scanning")
                    self.job.start()
                    if self.poll_timer:
                        self.poll_timer.stop()
                    self.poll_timer = self.set_interval(0.1, self.poll_scan)
            elif self.stage == "selection":
                self.show_stage("preview")
            elif self.stage == "preview":
                self.action_abandon()
        except (ValueError, TypeError):
            self.screen.query_one("#error", Static).update(
                "Configuration has unsupported source/destination values. Check the selected config; nothing was changed."
            )

    def poll_scan(self):
        job = self.job
        progress = job.take_progress()
        if progress and self.stage == "scanning" and isinstance(self.screen, Page):
            total = (
                str(progress.total)
                if progress.total is not None
                else "total not known yet"
            )
            self.screen.query_one("#progress", Static).update(
                f"{progress.phase.title()}: {progress.processed}/{total} files; {progress.files_found} found, {progress.skipped} skipped."
            )
        if not job.done.is_set():
            return
        if self.poll_timer:
            self.poll_timer.stop()
        self.poll_timer = None
        if job.cancelled.is_set() or self.stage != "scanning":
            return
        if not isinstance(self.screen, Page):
            # Resume delivers the result when the dialog closes; no idle polling.
            return
        if job.error:
            self.screen.query_one("#progress", Static).update(job.error)
        elif job.result is not None:
            self.draft.accept_scan(job.result, self.pending_key)
            self.show_stage("selection")

    def on_unmount(self):
        if self.poll_timer:
            self.poll_timer.stop()
        if self.job:
            self.job.close()
