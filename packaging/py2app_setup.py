from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parents[1]
APP = [str(ROOT / "src/fourg_bridge/app/main.py")]

OPTIONS = {
    "argv_emulation": False,
    # The app is AppKit-only.  Excluding Tk prevents the python.org framework's
    # bundled Tcl/Tk static archives from entering (and breaking) code signing.
    "excludes": ["_tkinter", "tkinter", "test", "unittest"],
    "packages": ["fourg_bridge", "usb", "libusb_package"],
    "resources": [str(ROOT / "src/fourg_bridge/imessage/resources/relay.applescript")],
    "dist_dir": str(ROOT / "dist"),
    "bdist_base": str(ROOT / "build"),
    "plist": {
        "CFBundleDisplayName": "4G Bridge",
        "CFBundleIdentifier": "com.pameda.fourgbridge",
        "CFBundleName": "4G Bridge",
        "CFBundleShortVersionString": "0.1.7",
        "CFBundleVersion": "8",
        "LSMinimumSystemVersion": "15.0",
        "LSUIElement": True,
        "NSAppleEventsUsageDescription": (
            "用于将 QDC507 收到的短信转发到您指定的 iMessage 联系方式。"
        ),
        "NSHumanReadableCopyright": "Copyright © 2026 4G Bridge contributors",
        "LSApplicationCategoryType": "public.app-category.utilities",
    },
}

setup(name="4G Bridge", app=APP, options={"py2app": OPTIONS})
