import runpy
import tomllib
from pathlib import Path
from unittest.mock import Mock

from fourg_bridge import __build__, __version__
from fourg_bridge.ui.about import show_about


def test_package_version_matches_ui():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    assert metadata["project"]["version"] == __version__


def test_bundle_uses_same_version_and_build(monkeypatch):
    setup = Mock()
    monkeypatch.setattr("setuptools.setup", setup)
    root = Path(__file__).resolve().parents[1]
    runpy.run_path(str(root / "packaging/py2app_setup.py"))
    metadata = setup.call_args.kwargs["options"]["py2app"]["plist"]
    assert metadata["CFBundleShortVersionString"] == __version__
    assert metadata["CFBundleVersion"] == __build__


def test_native_about_panel_has_visible_version(monkeypatch):
    application = Mock()
    factory = Mock()
    factory.sharedApplication.return_value = application
    monkeypatch.setattr("fourg_bridge.ui.about.AppKit.NSApplication", factory)
    show_about()
    options = application.orderFrontStandardAboutPanelWithOptions_.call_args.args[0]
    assert options["ApplicationVersion"] == __version__
    assert options["Version"] == __build__
    application.activateIgnoringOtherApps_.assert_called_once_with(True)
