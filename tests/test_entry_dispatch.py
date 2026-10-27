"""Tests for packaging/checkit_gui_entry.py CLI/GUI dispatch logic."""

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY_PATH = REPO_ROOT / "packaging" / "checkit_gui_entry.py"


def _load_entry():
    """Load the entry script as a module (it is top-level, not a package)."""
    spec = importlib.util.spec_from_file_location("checkit_gui_entry", ENTRY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def entry():
    return _load_entry()


class TestDispatch:
    def test_no_args_launches_gui(self, entry):
        with mock.patch.object(sys, "argv", ["checkit"]), \
             mock.patch("checkit.gui.main", return_value=0) as gui_main, \
             mock.patch("checkit.cli.main") as cli_main:
            assert entry.main() == 0
            gui_main.assert_called_once_with([])
            cli_main.assert_not_called()

    def test_gui_flags_launch_gui(self, entry):
        for argv in (["--debug"], ["--backend", "gtk"], ["--check-backend"]):
            with mock.patch.object(sys, "argv", ["checkit", *argv]), \
                 mock.patch("checkit.gui.main", return_value=0) as gui_main, \
                 mock.patch("checkit.cli.main") as cli_main:
                assert entry.main() == 0
                gui_main.assert_called_once_with(argv)
                cli_main.assert_not_called()

    @pytest.mark.parametrize("sub", ["run", "crawl", "distill", "settings"])
    def test_subcommands_route_to_cli(self, entry, sub):
        argv = [sub, "https://example.com"]
        with mock.patch.object(sys, "argv", ["checkit", *argv]), \
             mock.patch("checkit.cli.main", return_value=0) as cli_main, \
             mock.patch("checkit.gui.main") as gui_main:
            assert entry.main() == 0
            cli_main.assert_called_once_with(argv)
            gui_main.assert_not_called()

    @pytest.mark.parametrize("flag", ["--version", "--help", "-h"])
    def test_global_flags_route_to_cli(self, entry, flag):
        with mock.patch.object(sys, "argv", ["checkit", flag]), \
             mock.patch("checkit.cli.main", return_value=0) as cli_main, \
             mock.patch("checkit.gui.main") as gui_main:
            assert entry.main() == 0
            cli_main.assert_called_once_with([flag])
            gui_main.assert_not_called()
