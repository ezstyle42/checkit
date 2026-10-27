"""PyInstaller entry script for the checkit app.

PyInstaller runs this as a top-level script, so it must not use relative
imports. With no arguments (or GUI flags like --debug/--backend/
--check-backend) it launches the GUI; with a CLI subcommand or global CLI
flag (run, crawl, distill, settings, --version, --help) it acts as the
`checkit` CLI — the single executable serves both.
"""

import sys

CLI_SUBCOMMANDS = {"run", "crawl", "distill", "settings"}
CLI_GLOBAL_FLAGS = {"--version", "--help", "-h"}


def main() -> int:
    argv = sys.argv[1:]
    first = argv[0] if argv else ""
    if first in CLI_SUBCOMMANDS or first in CLI_GLOBAL_FLAGS:
        from checkit.cli import main as cli_main
        return cli_main(argv)
    from checkit.gui import main as gui_main
    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
