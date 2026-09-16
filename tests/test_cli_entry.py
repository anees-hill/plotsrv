from __future__ import annotations

from plotsrv import cli_entry


def test_bare_command_prints_root_help(capsys) -> None:
    assert cli_entry.main([]) == 0

    output = capsys.readouterr().out
    assert "usage: plotsrv" in output
    assert "commands:" in output
    assert "run" in output
    assert "watch" in output


def test_root_help(capsys) -> None:
    assert cli_entry.main(["--help"]) == 0

    assert "Documentation: https://docs.plotsrv.com" in capsys.readouterr().out


def test_version(capsys) -> None:
    assert cli_entry.main(["--version"]) == 0

    output = capsys.readouterr().out.strip()
    assert output.startswith("plotsrv ")


def test_full_command_delegates(monkeypatch) -> None:
    from plotsrv import cli

    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda args: seen.append(args) or 7)

    assert cli_entry.main(["run", "."]) == 7
    assert seen == [["run", "."]]


def test_all_help_paths_stay_lightweight(tmp_path):
    """A cold help process must never import runtime or optional wizard dependencies."""
    import subprocess
    import sys
    from plotsrv.cli_help import HELP

    for command in ["", *HELP, "--version"]:
        args = command.split() + ([] if command == "--version" else ["--help"])
        code = '''
import sys
class BlockRuntime:
    def find_spec(self, fullname, path=None, target=None):
        roots = ('plotsrv.cli', 'plotsrv.config', 'plotsrv.settings',
                 'plotsrv.config_wizard', 'plotsrv.ui_customiser', 'plotsrv.server',
                 'plotsrv.discovery', 'plotsrv.publisher_agent',
                 'pandas', 'numpy', 'matplotlib', 'fastapi', 'uvicorn', 'textual')
        if any(fullname == root or fullname.startswith(root + '.') for root in roots):
            raise AssertionError('Help imported ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
from plotsrv.cli_entry import main
main(sys.argv[1:])
'''
        result = subprocess.run(
            [sys.executable, "-c", code, *args], cwd=tmp_path,
            text=True, capture_output=True, timeout=10,
        )
        assert result.returncode == 0, (command, result.stderr)
        assert ("plotsrv " if command == "--version" else "usage: plotsrv") in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_help_catalogue_covers_parser_and_examples():
    import argparse
    import shlex
    from plotsrv.cli_help import COMMANDS, HELP
    from plotsrv.cli_parser import build_parser

    parser = build_parser()
    found = set()
    def visit(current, path=""):
        if path:
            found.add(path)
            assert current.description and current.epilog, path
            for action in current._actions:
                if not isinstance(action, argparse._SubParsersAction):
                    assert action.help, (path, action.dest)
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                if not path:
                    assert set(action.choices) == set(COMMANDS)
                for name, child in action.choices.items():
                    visit(child, (path + " " + name).strip())
    visit(parser)
    assert found == set(HELP)
    for _, examples in HELP.values():
        for line in examples.splitlines():
            if line.startswith("plotsrv ") and not line.endswith("--help"):
                parser.parse_args(shlex.split(line)[1:])
