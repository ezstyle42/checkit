"""Tests for GUI backend selection and js_api wiring (headless)."""

import sys
from unittest import mock

import pytest

from checkit import gui
from checkit.gui import GuiBridge, check_backend


class TestCheckBackend:
    def test_returns_expected_keys(self):
        status = check_backend()
        assert set(status) == {"qt", "gtk", "cocoa", "winforms", "error"}
        assert isinstance(status["qt"], bool)

    def test_qt_true_when_importable(self):
        with mock.patch.dict(sys.modules, {
            "qtpy": mock.MagicMock(),
            "qtpy.QtCore": mock.MagicMock(),
            "webview.platforms.qt": mock.MagicMock(),
        }):
            status = check_backend()
            assert status["qt"] is True
            assert status["error"] is None

    def test_qt_false_with_error_message_when_broken(self):
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "qtpy" or name.startswith("qtpy."):
                raise ImportError("No Qt bindings could be found")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            status = check_backend()
            assert status["qt"] is False
            assert status["error"] is not None
            assert "Qt bindings" in status["error"]

    def test_gtk_only_checked_on_linux(self):
        with mock.patch.object(sys, "platform", "darwin"):
            status = check_backend()
            # gtk key exists but should remain False on non-Linux
            assert status["gtk"] is False


class TestLaunchWiring:
    def test_launch_passes_js_api_and_forces_qt(self):
        bridge_holder = {}

        fake_webview = mock.MagicMock()

        def fake_create_window(title, url, **kwargs):
            bridge_holder["js_api"] = kwargs.get("js_api")
            bridge_holder["url"] = url
            return mock.MagicMock()

        fake_webview.create_window = fake_create_window

        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            gui.launch(debug=False, force_backend="qt")

        # js_api must be the GuiBridge so the JS can call window.pywebview.api.*
        assert isinstance(bridge_holder["js_api"], GuiBridge)
        # webview.start must be called with gui='qt'
        fake_webview.start.assert_called_once_with(gui="qt", debug=False)
        # URL must point at the bundled frontend
        assert "index.html" in bridge_holder["url"]

    def test_launch_wraps_backend_errors_with_guidance(self):
        fake_webview = mock.MagicMock()
        fake_webview.create_window.return_value = mock.MagicMock()
        fake_webview.start.side_effect = Exception("No backend")

        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            with pytest.raises(RuntimeError) as exc_info:
                gui.launch(debug=False)

        msg = str(exc_info.value)
        assert "Could not start the GUI" in msg
        assert "checkit run" in msg  # points to CLI fallback

    def test_launch_uses_requested_backend(self):
        fake_webview = mock.MagicMock()
        fake_webview.create_window.return_value = mock.MagicMock()

        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            gui.launch(debug=True, force_backend="gtk")

        fake_webview.start.assert_called_once_with(gui="gtk", debug=True)


class TestMainCli:
    def test_check_backend_flag(self, capsys):
        rc = gui.main(["--check-backend"])
        out = capsys.readouterr().out
        assert '"qt"' in out
        # rc is 0 if qt or gtk available, 1 otherwise — just check it's 0 or 1
        assert rc in (0, 1)

    def test_backend_choices(self):
        with pytest.raises(SystemExit):
            gui.main(["--backend", "bogus"])
