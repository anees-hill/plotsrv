# src/plotsrv/discovery.py
from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .contracts import SourceMetadata, ViewDescriptor


@dataclass(frozen=True, slots=True)
class DiscoveredView:
    kind: str  # unknown until a runtime value establishes capabilities
    label: str
    section: str | None
    view_id: str | None = None
    source: SourceMetadata | None = None
    description: str | None = None

    def descriptor(self) -> ViewDescriptor:
        from .store import normalize_view_id

        return ViewDescriptor(
            view_id=normalize_view_id(
                self.view_id, section=self.section, label=self.label
            ),
            label=self.label,
            section=self.section,
            kind=self.kind,
            source=self.source,
            description=self.description,
        )


def _extract_kw_str(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg != name:
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _extract_kw_int(call: ast.Call, name: str) -> int | None:
    for kw in call.keywords:
        if kw.arg != name:
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return kw.value.value
    return None


def _decorator_name(d: ast.expr) -> str | None:
    """
    Return decorator function name for:
       @view(...)
       @ps.view(...)
    """
    if isinstance(d, ast.Call):
        fn = d.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return d.attr
    return None


def _call_name(call: ast.Call) -> str | None:
    """
    Return call function name for:
       publish_view(...)
       ps.publish_view(...)
       plotsrv.publish_view(...)
    """
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _extract_publish_view_discovery(call: ast.Call) -> DiscoveredView | None:
    """
    Extract a discoverable view from a publish_view(...) call.

    Only literal string label/section/view_id values are supported. Dynamic
    labels are intentionally ignored because discovery is static and does not
    execute user code.
    """
    if _call_name(call) != "publish_view":
        return None

    view_id = _extract_kw_str(call, "view_id")
    label = _extract_kw_str(call, "label")
    section = _extract_kw_str(call, "section")

    if view_id:
        if ":" in view_id:
            sec, lab = view_id.split(":", 1)
            section = section or (sec.strip() or None)
            label = label or (lab.strip() or view_id)
        else:
            label = label or view_id

    if not label:
        return None

    declared_kind = _extract_kw_str(call, "kind")
    return DiscoveredView(
        kind=(
            declared_kind
            if declared_kind in ("plot", "table", "artifact")
            else "unknown"
        ),
        label=label,
        section=section,
        view_id=view_id,
    )


# Structural budgets apply to the scan, including enumeration and diagnostics.
MAX_SCAN_FILES = 10_000
MAX_SCAN_ENTRIES = 100_000
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_SCAN_ISSUES = 128
MAX_AST_NODES = 100_000
PRUNED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
    }
)


@dataclass(frozen=True, slots=True)
class DiscoveryProgress:
    phase: str
    processed: int
    total: int | None
    files_found: int
    skipped: int
    elapsed_s: float


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    path: str
    line: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    views: tuple[DiscoveredView, ...]
    issues: tuple[DiscoveryIssue, ...]
    issue_count: int
    processed: int
    total: int
    bytes_read: int
    cancelled: bool
    limited: bool

    @property
    def complete(self) -> bool:
        return not self.cancelled and not self.limited


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    """Conservative lexical evidence, not execution or data-flow inference."""
    bindings: dict[str, str] = {}
    ambiguous = set()
    modules = {
        "plotsrv",
        "plotsrv.publisher",
        "plotsrv.decorators",
        "plotsrv.streams",
        "plotsrv.streams.api",
    }
    top_level = set(tree.body)
    wildcard = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    wildcard = True
                    continue
                name = alias.asname or (
                    alias.name.split(".")[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                if node not in top_level:
                    ambiguous.add(name)
                    continue
                if isinstance(node, ast.Import) and alias.name in modules:
                    value = alias.name if alias.asname else "plotsrv"
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module in modules
                    and alias.name in {"view", "publish_view", "stream_view"}
                ):
                    value = node.module + "." + alias.name
                else:
                    ambiguous.add(name)
                    continue
                if name in bindings and bindings[name] != value:
                    ambiguous.add(name)
                bindings[name] = value
        elif isinstance(node, ast.Attribute) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                ambiguous.add(root.id)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            ambiguous.add(node.id)
        elif isinstance(node, ast.arg):
            ambiguous.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ambiguous.add(node.name)
    return (
        {}
        if wildcard
        else {key: value for key, value in bindings.items() if key not in ambiguous}
    )


def _api_name(expr: ast.expr, bindings: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Call):
        expr = expr.func
    parts = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name) or expr.id not in bindings:
        return None
    qualified = ".".join([bindings[expr.id], *reversed(parts)])
    allowed = {
        "plotsrv.view",
        "plotsrv.decorators.view",
        "plotsrv.publish_view",
        "plotsrv.publisher.publish_view",
        "plotsrv.stream_view",
        "plotsrv.streams.stream_view",
        "plotsrv.streams.api.stream_view",
    }
    return qualified.rsplit(".", 1)[-1] if qualified in allowed else None


def _literal_metadata(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg is None:
            return False
        if kw.arg in {"view_id", "label", "section"}:
            if not isinstance(kw.value, ast.Constant) or not (
                kw.value.value is None or isinstance(kw.value.value, str)
            ):
                return False
    return True


def scan_sources(
    root: str | Path,
    *,
    on_progress=None,
    on_issue=None,
    cancelled=None,
    include_pruned: bool = False,
) -> DiscoveryResult:
    """Enumerate once, read bounded source, and report candidates without imports.

    Cancellation is a callable returning bool or an Event with is_set(). Partial
    results are reviewable; manifest construction refuses cancelled/limited scans.
    """
    import os
    import stat
    import time
    from .contracts import MAX_CATALOGUE_VIEWS
    from .source_targets import resolve_source_target

    started = time.monotonic()
    files: list[Path] = []
    found: list[DiscoveredView] = []
    issues: list[DiscoveryIssue] = []
    issue_count = processed = skipped = total_bytes = entries = 0
    limited = was_cancelled = False

    def stopping():
        nonlocal was_cancelled
        was_cancelled = bool(
            cancelled and (cancelled() if callable(cancelled) else cancelled.is_set())
        )
        return was_cancelled

    def issue(path, reason, line=None):
        nonlocal issue_count, skipped
        issue_count += 1
        skipped += 1
        if len(issues) < MAX_SCAN_ISSUES:
            entry = DiscoveryIssue(str(path), line, reason)
            issues.append(entry)
            if on_issue:
                on_issue(entry)

    def progress(phase, total=None):
        if on_progress:
            on_progress(
                DiscoveryProgress(
                    phase,
                    processed,
                    total,
                    len(files),
                    skipped,
                    time.monotonic() - started,
                )
            )

    progress("enumerating")
    rootp = resolve_source_target(root)
    stack = [rootp] if rootp.is_dir() else []
    if rootp.is_file() and rootp.suffix == ".py":
        files.append(rootp)
    while stack and not stopping() and not limited:
        directory = stack.pop()
        try:
            with os.scandir(directory) as children:
                for entry in children:
                    if stopping():
                        break
                    entries += 1
                    if entries > MAX_SCAN_ENTRIES:
                        limited = True
                        issue(directory, "entry_limit")
                        break
                    if entries % 128 == 0:
                        progress("enumerating")
                    if entry.is_symlink():
                        skipped += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if include_pruned or entry.name not in PRUNED_DIRECTORIES:
                            stack.append(Path(entry.path))
                        else:
                            skipped += 1
                    elif entry.name.endswith(".py") and entry.is_file(
                        follow_symlinks=False
                    ):
                        if len(files) >= MAX_SCAN_FILES:
                            limited = True
                            issue(directory, "file_count_limit")
                            break
                        files.append(Path(entry.path))
        except OSError:
            issue(directory, "unreadable_directory")
    files.sort()
    if not was_cancelled and not limited:
        progress("scanning", len(files))
        for path in files:
            if stopping():
                break
            try:
                # O_NONBLOCK avoids hanging if a source is replaced with a FIFO.
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_NONBLOCK", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                with os.fdopen(os.open(path, flags), "rb") as source_file:
                    before = os.fstat(source_file.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise OSError("not a regular source")
                    if before.st_size > MAX_SOURCE_BYTES:
                        issue(path, "source_byte_limit")
                        continue
                    raw = source_file.read(
                        min(before.st_size, MAX_SCAN_BYTES - total_bytes) + 1
                    )
                    after = os.fstat(source_file.fileno())
                total_bytes += len(raw)
                if total_bytes > MAX_SCAN_BYTES:
                    limited = True
                    issue(path, "scan_byte_limit")
                    break
                if len(raw) > MAX_SOURCE_BYTES:
                    issue(path, "source_byte_limit")
                    continue
                if len(raw) != before.st_size or (
                    before.st_size,
                    before.st_mtime_ns,
                ) != (after.st_size, after.st_mtime_ns):
                    issue(path, "source_changed")
                    continue
                tree = ast.parse(raw, filename=str(path))
                nodes = []
                for node in ast.walk(tree):
                    if len(nodes) >= MAX_AST_NODES:
                        raise ValueError("ast_node_limit")
                    nodes.append(node)
                    if len(nodes) % 256 == 0 and stopping():
                        break
                if was_cancelled:
                    break
                bindings = _import_bindings(tree)
                for node in nodes:
                    declarations = []
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        declarations = [(dec, node) for dec in node.decorator_list]
                    elif isinstance(node, ast.Call):
                        declarations = [(node, None)]
                    for declaration, owner in declarations:
                        api = _api_name(declaration, bindings)
                        candidate_name = _decorator_name(declaration)
                        if api is None:
                            if candidate_name in {
                                "view",
                                "publish_view",
                                "stream_view",
                            } and (owner is not None or candidate_name != "view"):
                                issue(
                                    path,
                                    "unresolved_binding",
                                    getattr(declaration, "lineno", None),
                                )
                            continue
                        if (owner is None and api == "view") or (
                            owner is not None and api != "view"
                        ):
                            continue
                        call = (
                            declaration if isinstance(declaration, ast.Call) else None
                        )
                        if call is not None and not _literal_metadata(call):
                            issue(path, "unresolved_metadata", declaration.lineno)
                            continue
                        vid = _extract_kw_str(call, "view_id") if call else None
                        label = _extract_kw_str(call, "label") if call else None
                        section = _extract_kw_str(call, "section") if call else None
                        description = None
                        kind = "unknown"
                        if owner is not None:
                            label = label or owner.name
                            doc = ast.get_docstring(owner, clean=True)
                            if doc:
                                description = " ".join(doc.split("\n\n", 1)[0].split())[
                                    :2048
                                ]
                        elif api == "stream_view":
                            source = _extract_kw_str(call, "source")
                            if not label and source:
                                label = Path(source).stem
                            label = label or vid
                            section = section or "stream"
                            kind = "stream"
                        else:
                            if vid:
                                sec, separator, lab = vid.partition(":")
                                section = section or (sec if separator else None)
                                label = label or (lab if separator else vid)
                            declared = _extract_kw_str(call, "kind")
                            kind = (
                                declared
                                if declared in {"plot", "table", "artifact"}
                                else "unknown"
                            )
                        if not label:
                            issue(path, "unresolved_identity", declaration.lineno)
                            continue
                        view = DiscoveredView(
                            kind,
                            label,
                            section,
                            vid,
                            SourceMetadata(basename=path.name, source_type="python"),
                            description,
                        )
                        try:
                            view.descriptor()
                        except ValueError:
                            issue(path, "invalid_metadata", declaration.lineno)
                            continue
                        if len(found) >= MAX_CATALOGUE_VIEWS:
                            limited = True
                            issue(path, "catalogue_limit")
                            break
                        found.append(view)
                    if limited:
                        break
            except OSError:
                issue(path, "unreadable_source")
            except (SyntaxError, UnicodeError):
                issue(path, "invalid_python")
            except (ValueError, RecursionError):
                issue(path, "ast_limit")
            finally:
                processed += 1
                progress("scanning", len(files))
            if limited:
                break
    progress(
        "cancelled" if was_cancelled else "limited" if limited else "complete",
        len(files),
    )
    found.sort(key=lambda x: ((x.section or ""), x.label))
    return DiscoveryResult(
        tuple(found),
        tuple(issues),
        issue_count,
        processed,
        len(files),
        total_bytes,
        was_cancelled,
        limited,
    )


def discover_views(root: str | Path, **kwargs) -> list[DiscoveredView]:
    """Compatibility list API; partial scans never become registration silently."""
    result = scan_sources(root, **kwargs)
    if not result.complete:
        raise ValueError(
            "Discovery cancelled or reached a scan limit; narrow the source scope"
        )
    return list(result.views)
