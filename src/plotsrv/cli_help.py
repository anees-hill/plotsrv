"""Static CLI guidance: safe to import without server, discovery or UI dependencies."""

import argparse

COMMANDS = {
    "run": "Discover and serve project views on this machine",
    "serve": "Host a server receiving data from publishers",
    "publish": "Register project views and send watched files to an existing server",
    "watch": "Serve a file or directory, or publish it to another server",
    "config": "Configure plotsrv with prompts, the browser editor or file utilities",
    "store": "Inspect or clear locally persisted data",
}

ROOT_DESCRIPTION = "plotsrv - inspect data, files, and live outputs in your browser"
ROOT_EPILOG = (
    "commands:\n" + "\n".join(f"  {name:<8}{summary}" for name, summary in COMMANDS.items())
    + "\n\nGetting started:\n"
    "  plotsrv config init               Guided terminal configuration\n"
    "  plotsrv config ui                 Browser editor for appearance and navigation\n"
    "  plotsrv run ./src                 Discover and serve a local project\n"
    "  plotsrv watch docs/               Browse supported files in a directory\n"
    "  plotsrv serve --host 0.0.0.0       Host a server for other machines\n"
    "  plotsrv publish --destination https://plots.example.org\n"
    "                                   Send configured sources to an existing server\n"
    "\nRun 'plotsrv COMMAND --help' for options and examples.\n"
    "Documentation: https://docs.plotsrv.com"
)

# Descriptions explain roles; examples use the same parser as real invocations.
HELP = {
    "run": (
        "Start a local server and discover @view declarations from a project. "
        "Passive mode scans without executing the target; your running application "
        "publishes the data. Callable mode executes the target in a subprocess. "
        "Configured discovery and watches are used unless explicitly overridden.",
        "plotsrv run\nplotsrv run ./src\nplotsrv run package.module:build --mode callable --keep-alive\n"
        "plotsrv run ./src --watch results.csv\n\n"
        "Use 'serve' for a server without project discovery, or 'publish' to send to another server.",
    ),
    "serve": (
        "Host the browser UI and receive published data over HTTP(S). This command "
        "does not scan a project, execute application code or start configured watches. "
        "Configure storage, admission, checks and authentication in the server config.",
        "plotsrv serve\nplotsrv serve --config server.yml --host 0.0.0.0 --port 8000\n\n"
        "Run your publishing application or 'plotsrv publish' on the source machine.",
    ),
    "publish": (
        "Register a catalogue of project views and publish configured watched files "
        "to an existing server. Discovery is static: application code is not executed. "
        "Your application publishes its own live objects. With no watches, this command "
        "exits after registration; otherwise it runs until Ctrl+C. It never starts a server.",
        "plotsrv publish --config publisher.yml\n"
        "plotsrv publish ./src --destination https://plots.example.org --bearer-token-env PLOTSRV_TOKEN\n"
        "plotsrv publish --no-discovery\n\n"
        "Destination uses publisher-settings.destination when configured, otherwise http://127.0.0.1:8000. Files are read on this machine; "
        "the server does not need access to their paths. Use --seal-catalogue only with the "
        "complete reviewed set of IDs from every contributing project.",
    ),
    "watch": (
        "Watch a file or discover supported files in a directory and show live views. "
        "Without a remote destination, starts a local server. With --destination or "
        "publisher-settings.destination, sends bounded content to an existing server; "
        "no shared filesystem is needed. Stop with Ctrl+C.",
        "plotsrv watch results.csv\nplotsrv watch app.log --tail\n"
        "plotsrv watch docs/ --max-depth 2 --max-views 32\n"
        "plotsrv watch docs/ --include '*.md'\n"
        "plotsrv watch query.sql --destination https://plots.example.org\n\n"
        "Directory discovery runs once at startup; restart to discover added files. "
        "Subfolders become sections (nested folders use names such as reference/api). "
        "Documents, tables, images, text/logs and supported code files are included. "
        "Hidden entries, symlinks and unknown extensions are skipped. Discovery stops "
        "at 10,000 entries or the view limit. Code is displayed, never executed. "
        "Remote watches always send bounded previews; file materialization is local only.",
    ),
    "config": (
        "Create or update configuration. Choose 'init' for guided terminal setup, "
        "'ui' for browser-based appearance/navigation editing, or the file utilities "
        "for starter templates and discovered per-view settings. The CLI wizard needs no extra dependency.",
        "plotsrv config init\nplotsrv config ui\nplotsrv config create\n"
        "plotsrv config populate --help",
    ),
    "config init": (
        "Sequential setup for publishing to another "
        "server, hosting a server, or both. Choose discovery, watches and relevant settings, "
        "then review changes before confirming a save. Existing files are backed up.",
        "plotsrv config init\nplotsrv config init ./src --config project.yml\n\n"
        "An optional target focuses static discovery; server-only setup can scan when local source exists. "
        "For a custom filename, pass --config project.yml to subsequent commands too.",
    ),
    "config ui": (
        "Launch a temporary browser editor for server appearance and navigation settings. "
        "Review changes before saving to config; this is separate from the CLI wizard "
        "or the normal data server. Stop the editor with Ctrl+C.",
        "plotsrv config ui\nplotsrv config ui --config server.yml --host 0.0.0.0 --port 8766 --no-open\n\n"
        "Use the printed editor URL to connect. Use 'config init' for deployment, sources and storage.",
    ),
    "config create": (
        "Write a starter YAML configuration without launching a wizard. Existing files "
        "are not overwritten unless --force is supplied.",
        "plotsrv config create\nplotsrv config create --config project.yml --expanded",
    ),
    "config populate": (
        "Statically discover @view declarations and populate one configuration section. "
        "Merge mode adds missing view entries while preserving existing entries; replace "
        "mode replaces that section's per-view mapping. Review the confirmation before writing.",
        "plotsrv config populate freshness ./src\nplotsrv config populate storage ./src\n"
        "plotsrv config populate limits ./src",
    ),
    "config populate freshness": (
        "Populate freshness-settings.views from discovered declarations. Merge preserves "
        "existing view settings; replace rebuilds this per-view mapping.",
        "plotsrv config populate freshness ./src --expected-every 5m --warn-after 10m --overdue-after 30m",
    ),
    "config populate storage": (
        "Populate storage-settings.views from discovered declarations. Merge preserves "
        "existing view settings; replace rebuilds this per-view mapping.",
        "plotsrv config populate storage ./src --keep-last 10 --min-store-interval 1m",
    ),
    "config populate limits": (
        "Populate per-view truncation settings from discovered declarations. Merge preserves "
        "existing view settings; replace rebuilds this per-view mapping.",
        "plotsrv config populate limits ./src --text 100000 --markdown 200000",
    ),
    "store": (
        "Inspect or delete data in this machine's configured storage directory. "
        "These commands operate on local disk, not a remote server. Put --config and "
        "--name before the storage subcommand.",
        "plotsrv store stats\nplotsrv store --config server.yml list\n"
        "plotsrv store list --view 'reports:daily'",
    ),
    "store stats": (
        "Show usage and counts for the configured local storage directory.",
        "plotsrv store stats\nplotsrv store --config server.yml stats",
    ),
    "store list": (
        "List persisted latest views, snapshots and stream sessions. Supply --view "
        "to inspect one view's stored history.",
        "plotsrv store list\nplotsrv store list --view 'reports:daily'",
    ),
    "store clear": (
        "Delete persisted latest state, snapshot history and stream history for "
        "--view or --all. Prompts for confirmation unless --yes is supplied.",
        "plotsrv store clear --view 'reports:daily'\nplotsrv store --config server.yml clear --all",
    ),
}


class _CommandHelpFormatter(argparse.HelpFormatter):
    """Wrap prose to terminal width while keeping example commands on separate lines."""

    def _fill_text(self, text, width, indent):
        if not text.startswith("Examples:"):
            return super()._fill_text(text, width, indent)
        examples, separator, notes = text.partition("\n\n")
        return examples + (
            separator + super()._fill_text(notes, width, indent) if separator else ""
        )


def command_help(command: str) -> dict:
    description, examples = HELP[command]
    commands, separator, notes = examples.partition("\n\n")
    return {
        "description": description,
        "epilog": "Examples:\n  " + commands.replace("\n", "\n  ") + separator + notes,
        "formatter_class": _CommandHelpFormatter,
    }
