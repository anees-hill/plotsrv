"""Settings, per-view forms and the explicit review/save end of the wizard."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static

from .draft import FIELDS
from .schema import PAGES, fields_for
from .saving import DELETE, SaveError, prepare, read_snapshot, save
from .tui import Page, Roles


class SaveConfirmation(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Return to review")]

    def compose(self):
        with Vertical(id="dialog"):
            yield Static(
                "Write exactly the reviewed configuration? Existing files receive a unique backup. Running services will not change."
            )
            yield Button("Return to review", id="cancel-save", variant="primary")
            yield Button("Save configuration", id="confirm-save")

    def on_mount(self):
        self.query_one("#cancel-save").focus()

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "confirm-save")


class WorkflowPage(Page):
    def __init__(self, stage, *, view_id=None, advanced=False):
        super().__init__(stage)
        self.view_id = view_id
        self.advanced = advanced
        self.specs = []
        self.menu = []

    def compose(self):
        draft = self.app.draft
        title = self.stage.title() + (f" · {self.view_id}" if self.view_id else "")
        yield Static(Text("plotsrv configuration · " + title), id="title")
        with VerticalScroll(id="content"):
            if self.stage in PAGES:
                self.specs = fields_for(self.stage, draft, self.view_id)
                if self.stage == "publisher":
                    yield Static(
                        "Publisher-side budgets only. Receiver storage and UI are configured on the server. Missing key values may be set later on that machine; only environment names are saved."
                    )
                if self.stage == "server":
                    yield Static(
                        "Loopback with no key is normal. For a remote bind, choose a key environment name or explicitly allow unauthenticated publishers on a trusted private endpoint. A publisher key is not dashboard authentication."
                    )
                if self.stage == "checks":
                    yield Static(
                        "Existing checks-settings.rules and webhook-settings.destinations are preserved and validated. Edit those modest YAML schemas using the checks/webhooks guides; headers_env takes environment names. Endpoints and secret values are hidden here. Nothing is sent.\nAppearance: use ui-settings until the separate plotsrv config ui tool is available."
                    )
                if self.stage == "publish":
                    yield Static(
                        "Publisher process settings. Observe limits remain capped by the production model. Stream retry settings do not alter ordinary live publication or remote-watch backoff."
                    )
                for spec in self.specs:
                    yield Static(spec.label, id="label-" + spec.key)
                    value = draft.value(spec)
                    text = self.app.form_inputs.get(
                        (self.stage, self.view_id, spec.key), self.display(value, spec)
                    )
                    choices = spec.choices or (
                        ("true", "false") if spec.kind == "bool" else ()
                    )
                    if choices:
                        yield Select(
                            [
                                (
                                    (
                                        "Yes"
                                        if v == "true"
                                        else "No" if v == "false" else v
                                    ),
                                    v,
                                )
                                for v in choices
                            ],
                            value=text,
                            allow_blank=False,
                            id=spec.key,
                        )
                    else:
                        yield Input(text, id=spec.key, max_length=4096)
                if self.stage in ("storage", "freshness"):
                    if self.view_id:
                        yield Button(
                            "Use inherited settings for this view", id="inherit"
                        )
                    else:
                        yield Button("Per-view overrides", id="overrides")
                if (
                    self.stage in ("server", "publisher")
                    or self.stage in ("storage", "freshness")
                    and not self.view_id
                    and not draft.known_ids()
                ):
                    yield Static(
                        "Explicit logical IDs (also available for per-view settings). In server dynamic mode these do not restrict admission; locked mode uses the complete list.",
                        id="ids-help",
                    )
                    yield Static(
                        Text(
                            "\n".join(draft.configured_ids())
                            or "(none — locked servers may await explicit bootstrap)"
                        ),
                        id="manual-summary",
                    )
                    yield Input(
                        placeholder="Add one logical ID", id="manual-id", max_length=512
                    )
                    yield Button("Add ID", id="add-id")
                    yield Button("Remove last explicit ID", id="remove-id")
                    if self.stage == "server":
                        yield Button(
                            "Await publisher bootstrap instead of an ID list",
                            id="await-bootstrap",
                        )
            elif self.stage == "view_choices":
                self.menu = draft.known_ids()
                yield Static(
                    "Choose a logical view. Add manual IDs on the preceding page if no local catalogue is available."
                )
                yield Roles(*(Text(vid) for vid in self.menu), id="workflow-menu")
            elif self.stage == "ready":
                yield Static(
                    "Core setup complete. Review and save now, or explore advanced settings. All edits are still in memory."
                )
                yield Button("Review and save", id="review-path", variant="primary")
                yield Button("Advanced settings", id="advanced")
            elif self.stage == "advanced":
                self.menu = (
                    ["watch", "publish", "limits"]
                    if draft.role == "publisher"
                    else (
                        ["watch", "limits", "security", "checks", "server"]
                        if draft.role == "server"
                        else [
                            "watch",
                            "publish",
                            "limits",
                            "security",
                            "checks",
                            "server",
                        ]
                    )
                )
                yield Static(
                    "Settings apply only to the process reading this config. Appearance: use ui-settings until the separate plotsrv config ui tool is available."
                )
                yield Roles(*(name.title() for name in self.menu), id="workflow-menu")
                yield Button("Review and save", id="review-path")
            elif self.stage == "save_path":
                yield Static(
                    "Choose the config filename. Use --config with custom names. Relative source/storage paths are reviewed against the current config folder; source and destination files are checked again before writing."
                )
                yield Input(
                    self.app.save_path or str(draft.path),
                    id="save-path",
                    max_length=4096,
                )
            elif self.stage == "review":
                yield Static(Text(self.app.review.text), id="review-text")
                yield Static(
                    Text("Target: " + str(self.app.review.path)), id="review-target"
                )
                yield Button(
                    "Save this reviewed configuration",
                    id="save-reviewed",
                    variant="primary",
                )
                yield Button(
                    "Reload current file and review draft edits again",
                    id="reload-review",
                )
            elif self.stage == "saved":
                yield Static(Text(self.app.saved_message), id="saved-message")
            yield Static("", id="error", markup=False)
            with Horizontal(id="actions"):
                if self.stage != "saved":
                    yield Button("Back", id="back")
                if self.stage in PAGES or self.stage == "save_path":
                    yield Button(
                        "Review" if self.stage == "save_path" else "Next",
                        id="next",
                        variant="primary",
                    )
                if self.stage == "saved":
                    yield Button("Close", id="close-saved", variant="primary")
        with VerticalScroll(id="help-panel"):
            yield Static("", id="context-help", markup=False)
        yield Static("", id="legend", markup=False)

    @staticmethod
    def display(value, spec):
        if value is None:
            return "off" if spec.kind in ("duration", "keep") else ""
        return str(value).lower() if type(value) is bool else str(value)

    def on_mount(self, event):
        event.prevent_default()
        self.update_help()
        for spec in self.specs:
            self.mark_field(spec.key)
        self.enable_details()
        candidates = list(self.query("Input, Select, OptionList, Button"))
        if candidates:
            candidates[0].focus()

    def mark_field(self, key):
        spec = next(s for s in self.specs if s.key == key)
        widget = self.query_one("#" + key)
        value = widget.value
        try:
            changed = spec.parse(str(value)) != spec.default
        except ValueError:
            changed = True
        label = self.query_one("#label-" + key, Static)
        label.update(Text(spec.label + (" *" if changed else "")))
        label.set_class(changed, "modified")

    def enable_details(self):
        if self.stage not in ("storage", "freshness") or self.view_id:
            return
        enabled = self.query_one("#" + self.stage + "_enabled", Select).value == "true"
        for spec in self.specs[1:]:
            self.query_one("#" + spec.key).display = enabled
            self.query_one("#label-" + spec.key).display = enabled
        self.query_one("#overrides").display = enabled

    def update_help(self):
        key = self.focused.id if self.focused else None
        spec = next((s for s in self.specs if s.key == key), None)
        text = (
            spec.help(self.app.draft.origin(spec))
            if spec
            else "Tab / Shift+Tab moves through fields and actions. Enter activates the focused action. Changes stay in memory until explicit confirmation after Review. Back keeps draft choices; Ctrl+C/Q asks before abandoning."
        )
        if self.view_id and spec:
            text += " Per-view inheritance: reset removes this instance’s override and reveals its parent policy."
        self.query_one("#context-help", Static).update(text)
        self.query_one("#legend", Static).update(
            "Tab / Shift+Tab fields · Enter choose · Esc back · F1 help · Ctrl+C/Q abandon"
        )

    def changed(self, key, value):
        if any(s.key == key for s in self.specs):
            self.app.form_inputs[(self.stage, self.view_id, key)] = value
            self.mark_field(key)
            self.enable_details()

    def on_input_changed(self, event):
        event.prevent_default()
        self.changed(event.input.id, event.value)

    def on_select_changed(self, event):
        if event.value is not Select.BLANK:
            self.changed(event.select.id, event.value)

    def collect(self, strict=True):
        edits = {}
        try:
            for spec in self.specs:
                widget = self.query_one("#" + spec.key)
                # Disabled sections retain untouched settings, including legacy values.
                if not widget.display:
                    continue
                parsed = spec.parse(str(widget.value))
                if parsed != self.app.draft.value(spec) or (
                    self.app.draft.original is None
                    and not self.view_id
                    and not self.advanced
                ):
                    edits[spec.path] = parsed
            self.app.draft.update_edits(edits)
            return True
        except ValueError as error:
            if strict:
                self.query_one("#error", Static).update(spec.label + ": " + str(error))
            return False

    def back(self):
        if self.stage == "saved":
            self.app.exit(self.app.saved_message)
            return
        self.collect(strict=False)
        if self.stage == "save_path":
            self.app.save_path = self.query_one("#save-path", Input).value
        self.app.back_workflow()

    def advance(self):
        if not self.collect():
            return
        if self.stage in PAGES:
            if self.view_id or self.advanced:
                self.app.back_workflow()
                return
            following = {
                "server": "storage",
                "storage": "freshness",
                "freshness": "ready",
                "publisher": "ready",
            }
            self.app.go_workflow(following[self.stage])
        elif self.stage == "save_path":
            self.app.save_path = self.query_one("#save-path", Input).value
            try:
                self.app.review = prepare(self.app.draft, self.app.save_path)
                self.app.go_workflow("review")
            except (ValueError, OSError) as error:
                self.query_one("#error", Static).update(str(error))

    def on_option_list_option_selected(self, event):
        event.prevent_default()
        if event.option_list.id == "workflow-menu" and self.menu:
            choice = self.menu[event.option_index]
            if self.stage == "view_choices":
                self.app.go_workflow(self.app.override_section, view_id=choice)
            else:
                self.app.go_workflow(choice, advanced=True)

    def on_button_pressed(self, event):
        event.prevent_default()
        event.stop()
        action = event.button.id
        try:
            if action == "back":
                self.back()
            elif action == "next":
                self.advance()
            elif action == "advanced":
                self.app.go_workflow("advanced")
            elif action == "review-path":
                self.app.go_workflow("save_path")
            elif action == "overrides" and self.collect():
                self.app.override_section = self.stage
                self.app.go_workflow("view_choices")
            elif action == "inherit":
                self.app.draft.reset_overrides(self.specs, self.view_id)
                for spec in self.specs:
                    self.app.form_inputs.pop((self.stage, self.view_id, spec.key), None)
                self.app.back_workflow()
            elif action == "await-bootstrap":
                self.app.draft.manual_ids = None
                self.app.draft.edits[
                    ("server-settings", "admission", "allowed_ids")
                ] = None
                self.query_one("#manual-summary", Static).update(
                    "No configured ID manifest: a locked server will await explicit publisher bootstrap. An explicitly empty list would instead deny all IDs."
                )
            elif action == "add-id":
                self.app.draft.add_id(self.query_one("#manual-id", Input).value.strip())
                self.query_one("#manual-id", Input).value = ""
                self.query_one("#manual-summary", Static).update(
                    Text("\n".join(self.app.draft.configured_ids()))
                )
            elif action == "remove-id":
                self.app.draft.manual_ids = list(self.app.draft.configured_ids())[:-1]
                self.query_one("#manual-summary", Static).update(
                    Text("\n".join(self.app.draft.configured_ids()) or "(none)")
                )
            elif action == "save-reviewed":
                self.app.push_screen(SaveConfirmation(), self.confirm_save)
            elif action == "reload-review":
                from .draft import _load_bounded

                snapshot = read_snapshot(self.app.draft.path)
                document = _load_bounded(snapshot.raw) if snapshot.raw else {}
                self.app.draft.config = document
                self.app.draft.original = snapshot.raw
                self.app.draft.original_stamp = snapshot.stamp
                self.app.review = prepare(self.app.draft, self.app.save_path)
                self.query_one("#review-text", Static).update(
                    Text(self.app.review.text)
                )
                self.query_one("#error", Static).update(
                    "Review refreshed. Confirm the changes before saving."
                )
            elif action == "close-saved":
                self.app.exit(self.app.saved_message)
        except (ValueError, OSError) as error:
            self.query_one("#error", Static).update(str(error))

    def confirm_save(self, confirmed):
        if not confirmed:
            return
        try:
            backup = save(self.app.review)
            self.app.saved_message = (
                "Saved "
                + str(self.app.review.path)
                + ("\nBackup: " + str(backup) if backup else "")
                + "\n\n"
                + self.app.draft.commands(self.app.review.path)
            )
            self.app.go_workflow("saved")
        except SaveError as error:
            self.query_one("#error", Static).update(str(error))
