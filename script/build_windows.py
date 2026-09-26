"""Build only on Windows using reviewed, hash-locked PyInstaller dependencies."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0-preview.1"


def icon(path: Path) -> None:
    """Original blue signal-bars icon, no brand assets and no graphics dependencies."""
    size = 32
    pixels = bytearray()
    for y in reversed(range(size)):
        for x in range(size):
            inside = 2 <= x < 30 and 2 <= y < 30
            bars = any(
                left <= x < left + 3 and 25 - height <= y <= 25
                for left, height in ((7, 6), (12, 10), (17, 15), (22, 20))
            )
            pixels += bytes(
                (255, 255, 255, 255) if bars else (212, 120, 0, 255) if inside else (0, 0, 0, 0)
            )
    mask = bytes(4 * size)
    bitmap = (
        struct.pack(
            "<IIIHHIIIIII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0
        )
        + pixels
        + mask
    )
    path.write_bytes(
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(bitmap), 22)
        + bitmap
    )


def notices(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in (
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "altgraph",
        "pefile",
        "pywin32-ctypes",
        "packaging",
        "setuptools",
    ):
        dist = importlib.metadata.distribution(name)
        for file in dist.files or ():
            if any(word in file.name.lower() for word in ("license", "copying")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    shutil.copy2(source, target / (name + "-" + file.name))
    python_root = Path(sys.base_prefix)
    for source in (
        python_root / "LICENSE.txt",
        python_root / "tcl/tcl8.6/license.terms",
        python_root / "tcl/tk8.6/license.terms",
    ):
        if not source.is_file():
            raise RuntimeError(f"Missing runtime license: {source.name}")
        shutil.copy2(source, target / (source.parent.name + "-" + source.name))
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", target)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build Windows artifacts on Windows; cross compilation is not supported.")
    os.chdir(ROOT)
    work = ROOT / "build/windows"
    artifacts = ROOT / "artifacts"
    work.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    icon_path = work / "bridge.ico"
    icon(icon_path)
    notices(work / "licenses")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--noupx",
            "--windowed",
            "--onedir",
            "--name",
            "4G Bridge",
            "--paths",
            "src",
            "--distpath",
            "dist/windows",
            "--workpath",
            "build/windows/pyinstaller",
            "--specpath",
            "build/windows",
            "--icon",
            str(icon_path),
            "--add-data",
            f"{icon_path}{os.pathsep}fourg_bridge/windows",
            "--add-data",
            f"{work / 'licenses'}{os.pathsep}licenses",
            "--exclude-module",
            "fourg_bridge.imessage",
            "--exclude-module",
            "fourg_bridge.app",
            "--exclude-module",
            "fourg_bridge.ui",
            "--exclude-module",
            "usb",
            "--exclude-module",
            "objc",
            "script/windows_entry.py",
        ],
        check=True,
    )
    bundle = ROOT / "dist/windows/4G Bridge"
    shutil.copy2(ROOT / "WINDOWS.md", bundle / "README-Windows.md")
    # Exact uninstall manifest, never recursive deletion of an arbitrary directory.
    lines = ['Delete "$INSTDIR\\Uninstall.exe"']
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(bundle)).replace('"', '$\\"').replace("$", "$$")
            lines.append(f'Delete "$INSTDIR\\{relative}"')
    for path in sorted(
        (p for p in bundle.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        relative = str(path.relative_to(bundle)).replace("$", "$$")
        lines.append(f'RMDir "$INSTDIR\\{relative}"')
    (work / "uninstall-files.nsh").write_text("\n".join(lines), encoding="utf-8-sig")
    compiler = (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "NSIS/makensis.exe"
    )
    if not compiler.is_file():
        raise SystemExit("NSIS is not installed. Verify official source and obtain approval first.")
    subprocess.run(
        [str(compiler), "/INPUTCHARSET", "UTF8", "script/windows_installer.nsi"], check=True
    )
    shutil.make_archive(str(artifacts / f"4G-Bridge-{VERSION}-windows-x64-portable"), "zip", bundle)
    outputs = sorted(artifacts.glob(f"4G-Bridge-{VERSION}-windows-x64*"))
    checksums = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in outputs
        if p.suffix in (".exe", ".zip")
    ]
    (artifacts / "windows-SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
