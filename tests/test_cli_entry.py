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
