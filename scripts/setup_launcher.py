"""AI-AGENT Windows setup launcher — extract bundled zip and start services."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find_archive(base: Path) -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        embedded = Path(sys._MEIPASS) / "AI-AGENT-package.zip"
        if embedded.is_file():
            return embedded
    for name in ("AI-AGENT-package.zip", "aiagnet-win-package.zip"):
        p = base / name
        if p.is_file():
            return p
    matches = sorted(base.glob("aiagnet-win-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _extract_zip(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    # package_win_release creates aiagnet-win-YYYYMMDD-HHmm/ at zip root
    children = [p for p in dest.iterdir() if p.is_dir() and p.name.startswith("aiagnet-win-")]
    if len(children) == 1:
        return children[0]
    # flat layout fallback
    if (dest / "AI-AGENT.bat").is_file():
        return dest
    raise RuntimeError("Unexpected archive layout — missing aiagnet-win-* folder")


def _install_dir(base: Path) -> Path:
    custom = os.environ.get("AIAGNET_INSTALL_DIR", "").strip()
    if custom:
        return Path(custom)
    return base / "AI-AGENT"


def main() -> int:
    base = _base_dir()
    install_root = _install_dir(base)
    bat = install_root / "AI-AGENT.bat"

    if not bat.is_file():
        archive = _find_archive(base)
        if archive is None:
            print("ERROR: AI-AGENT-package.zip not found next to this installer.")
            print(f"Place the zip in: {base}")
            input("Press Enter to exit...")
            return 1
        print(f"Extracting {archive.name} -> {install_root} ...")
        if install_root.exists():
            shutil.rmtree(install_root, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix="aiagnet-extract-"))
        try:
            app_dir = _extract_zip(archive, tmp)
            shutil.move(str(app_dir), str(install_root))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("Extract complete.")

    if not bat.is_file():
        print(f"ERROR: {bat} not found after extract.")
        input("Press Enter to exit...")
        return 1

    print("Starting AI-AGENT (keep the service window open)...")
    print("Open http://localhost:3000 in your browser.")
    subprocess.Popen(
        ["cmd.exe", "/c", "start", "", str(bat)],
        cwd=str(install_root),
        shell=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
