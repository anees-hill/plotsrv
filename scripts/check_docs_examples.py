"""Check documentation snippet syntax, public API calls, and CLI arguments.

This does not execute example jobs, contact remote hosts, or resolve credentials.
Run complete examples separately when their behaviour changes.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
import inspect
from io import StringIO
from pathlib import Path
import re
import shlex
import textwrap

import yaml

import plotsrv as ps
from plotsrv.cli_parser import build_parser
from plotsrv.config_wizard.schema import validate_document
from plotsrv.config_wizard.saving import SaveError

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^(?P<indent> {0,4})```(?P<lang>[\w-]+)[^\n]*\n(?P<body>.*?)^(?P=indent)```[^\n]*$", re.M | re.S)


def check() -> None:
    errors = []
    counts = {"Python": 0, "YAML": 0, "CLI": 0, "configuration": 0}
    parser = build_parser()
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        text = path.read_text()
        imported = {}
        for match in FENCE.finditer(text):
            language = match["lang"]
            code = textwrap.dedent(match["body"])
            line = text[:match.start()].count("\n") + 2
            where = f"{path.relative_to(ROOT)}:{line}"
            try:
                if language == "python":
                    counts["Python"] += 1
                    tree = ast.parse(code)
                    imported.update({
                        alias.asname or alias.name: getattr(ps, alias.name)
                        for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module == "plotsrv"
                        for alias in node.names if alias.name != "*"
                    })
                    for node in ast.walk(tree):
                        if not isinstance(node, ast.Call):
                            continue
                        function = None
                        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "ps":
                            if node.func.attr not in ps.__all__:
                                raise ValueError(f"Unknown public name ps.{node.func.attr}")
                            function = getattr(ps, node.func.attr)
                        elif isinstance(node.func, ast.Name):
                            function = imported.get(node.func.id)
                        if function is None or any(isinstance(arg, ast.Starred) for arg in node.args) or any(kw.arg is None for kw in node.keywords):
                            continue
                        try:
                            inspect.signature(function).bind(
                                *[None for _ in node.args], **{kw.arg: None for kw in node.keywords}
                            )
                        except TypeError as error:
                            raise ValueError(f"{ast.unparse(node.func)}: {error}") from error
                elif language in {"yaml", "yml"}:
                    counts["YAML"] += 1
                    document = yaml.safe_load(code)
                    if isinstance(document, dict) and any(isinstance(key, str) and key.endswith("-settings") for key in document):
                        # The wizard shares production validators but never reads
                        # secret values or writes config during document review.
                        validate_document(document, None, path.parent, "combined")
                        names = {name for section in document.values() if isinstance(section, dict)
                                 for name in section.get("instances", {})}
                        for name in names:
                            validate_document(document, name, path.parent, "combined")
                        counts["configuration"] += 1
                elif language in {"bash", "sh", "shell"}:
                    for command in code.replace("\\\n", " ").splitlines():
                        args = shlex.split(command, comments=True)
                        if args[:2] == ["uv", "run"]:
                            args = args[2:]
                        if not args or args[0] != "plotsrv" or "..." in args:
                            continue
                        counts["CLI"] += 1
                        captured = StringIO()
                        with redirect_stdout(captured), redirect_stderr(captured):
                            try:
                                parser.parse_args(args[1:])
                            except SystemExit as error:
                                if error.code:
                                    raise ValueError(captured.getvalue().strip()) from error
            except (SyntaxError, ValueError, AttributeError, yaml.YAMLError, SaveError) as error:
                errors.append(f"{where}: {error}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Checked " + ", ".join(f"{count} {kind}" for kind, count in counts.items())
          + " snippets (syntax and API/CLI arguments; no remote execution).")


if __name__ == "__main__":
    check()
