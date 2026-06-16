"""AI-AGENT Windows all-in-one installer: Docker Desktop + pre-built images."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

DOCKER_DOWNLOAD_URL = (
    "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
)
COMPOSE_FILE = "docker-compose.desktop.yml"

_SCRIPTS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
try:
    from desktop_delivery import HTTP_PORT, admin_readme, build_env_text, compose_up_args  # noqa: E402
except ImportError:
    HTTP_PORT = 3000
    def build_env_text(**kwargs):  # type: ignore[misc]
        raise RuntimeError("desktop_delivery module missing")
    def admin_readme(token: str) -> str:  # type: ignore[misc]
        return token
    def compose_up_args() -> list[str]:  # type: ignore[misc]
        return ["up", "-d"]


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _install_dir(base: Path) -> Path:
    custom = os.environ.get("AIAGNET_INSTALL_DIR", "").strip()
    if custom:
        return Path(custom)
    return base / "AI-AGENT-Docker"


def _pause(msg: str = "Press Enter to exit...") -> None:
    try:
        input(msg)
    except EOFError:
        pass


def _log(msg: str) -> None:
    print(msg, flush=True)


def _find_archive(base: Path) -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        embedded = Path(sys._MEIPASS) / "AI-AGENT-package.zip"
        if embedded.is_file():
            return embedded
    for name in ("AI-AGENT-package.zip",):
        p = base / name
        if p.is_file():
            return p
    matches = sorted(
        base.glob("aiagnet-docker-win-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _extract_zip(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    for prefix in ("aiagnet-docker-win-", "aiagnet-win-"):
        children = [p for p in dest.iterdir() if p.is_dir() and p.name.startswith(prefix)]
        if len(children) == 1:
            return children[0]
    if (dest / COMPOSE_FILE).is_file() or (dest / "images").is_dir():
        return dest
    raise RuntimeError("Unexpected archive layout")


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    _log(f"  > {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=not sys.stdout.isatty(),
        check=check,
    )


def _which_docker() -> str | None:
    return shutil.which("docker")


def _docker_ready(timeout_sec: int = 600) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _which_docker():
            try:
                r = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r.returncode == 0:
                    return True
            except (subprocess.SubprocessError, OSError):
                pass
        time.sleep(5)
    return False


def _find_docker_desktop_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Docker"
        / "Docker"
        / "Docker Desktop.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Docker"
        / "Docker"
        / "Docker Desktop.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Docker"
        / "Docker Desktop.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _find_docker_installer(install_root: Path) -> Path | None:
    names = [
        install_root / "prerequisites" / "DockerDesktopInstaller.exe",
        install_root / "prerequisites" / "Docker Desktop Installer.exe",
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        names.extend(
            [
                Path(sys._MEIPASS) / "DockerDesktopInstaller.exe",
                Path(sys._MEIPASS) / "prerequisites" / "DockerDesktopInstaller.exe",
            ]
        )
    for p in names:
        if p.is_file():
            return p
    return None


def _download_docker_installer(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Downloading Docker Desktop installer (~500 MB)...")
    _log(f"  {DOCKER_DOWNLOAD_URL}")
    urllib.request.urlretrieve(DOCKER_DOWNLOAD_URL, dest)
    return dest


def _install_docker_desktop(installer: Path) -> None:
    _log("")
    _log("========================================")
    _log("  Step 1/3  Install Docker Desktop")
    _log("========================================")
    _log(f"Installer: {installer.name}")
    _log("This may take 5-15 minutes. Please wait...")
    _log("")

    # Per-user silent install — no admin required in most cases
    cmd = [
        str(installer),
        "install",
        "--accept-license",
        "--quiet",
        "--user",
        "--norestart",
    ]
    r = subprocess.run(cmd, text=True)
    if r.returncode not in (0, 1, 3010, 1641):  # 1641/3010 = reboot required
        _log(f"[WARN] Docker installer exit code: {r.returncode}")

    desktop = _find_docker_desktop_exe()
    if desktop:
        _log("Starting Docker Desktop...")
        subprocess.Popen([str(desktop)], shell=False)
    else:
        _log("Docker Desktop installed. Please start it from the Start menu if needed.")


def _ensure_docker(install_root: Path) -> bool:
    if _docker_ready(timeout_sec=15):
        _log("[OK] Docker is already running.")
        return True

    _log("Docker not ready — installing Docker Desktop...")
    installer = _find_docker_installer(install_root)
    if installer is None:
        cache = install_root / "prerequisites" / "DockerDesktopInstaller.exe"
        try:
            installer = _download_docker_installer(cache)
        except OSError as exc:
            _log(f"[ERROR] Failed to download Docker Desktop: {exc}")
            _log("Install manually: https://www.docker.com/products/docker-desktop/")
            return False

    _install_docker_desktop(installer)
    _log("Waiting for Docker engine (up to 10 min)...")
    if not _docker_ready(timeout_sec=600):
        _log("[ERROR] Docker did not start in time.")
        _log("  1. Open Docker Desktop from Start menu")
        _log("  2. Enable WSL 2 if prompted (Windows 10/11)")
        _log("  3. Re-run this installer")
        return False
    _log("[OK] Docker is running.")
    return True


def _compose_cmd() -> list[str]:
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                check=True,
                timeout=10,
            )
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, subprocess.SubprocessError, OSError):
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def _write_env(install_root: Path) -> str:
    token = secrets.token_hex(16)
    (install_root / ".env").write_text(build_env_text(setup_token=token), encoding="utf-8")
    (install_root / "SETUP_TOKEN.admin.txt").write_text(admin_readme(token), encoding="utf-8")
    return token


def _load_images(install_root: Path) -> None:
    images_dir = install_root / "images"
    if not images_dir.is_dir():
        raise FileNotFoundError(f"Missing images folder: {images_dir}")
    tars = sorted(images_dir.glob("*.tar"))
    if not tars:
        raise FileNotFoundError(f"No .tar images in {images_dir}")
    _log("")
    _log("========================================")
    _log("  Step 2/3  Load application images")
    _log("========================================")
    for tar in tars:
        _log(f"Loading {tar.name} ...")
        _run(["docker", "load", "-i", str(tar)], check=True)


def _start_services(install_root: Path) -> None:
    compose = _compose_cmd()
    compose_file = install_root / COMPOSE_FILE
    if not compose_file.is_file():
        raise FileNotFoundError(f"Missing {COMPOSE_FILE}")

    if not (install_root / ".env").is_file():
        _write_env(install_root)

    _log("")
    _log("========================================")
    _log("  Step 3/3  Start AI-AGENT services")
    _log("========================================")
    up_args = compose_up_args()
    _run(
        [*compose, "-f", str(compose_file), *up_args],
        cwd=install_root,
        check=True,
    )


def _wait_http(url: str, timeout_sec: int = 180) -> bool:
    import urllib.error

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(3)
    return False


def main() -> int:
    base = _base_dir()
    install_root = _install_dir(base)

    _log("")
    _log("========================================")
    _log("  AI-AGENT Windows Installer")
    _log("  (Docker + Application)")
    _log("========================================")
    _log("")

    marker = install_root / COMPOSE_FILE
    if not marker.is_file():
        archive = _find_archive(base)
        if archive is None:
            _log("ERROR: package zip not found.")
            _pause()
            return 1
        _log(f"Extracting {archive.name} -> {install_root}")
        if install_root.exists():
            shutil.rmtree(install_root, ignore_errors=True)
        tmp = Path(tempfile.mkdtemp(prefix="aiagnet-extract-"))
        try:
            app_dir = _extract_zip(archive, tmp)
            shutil.move(str(app_dir), str(install_root))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _log("Extract complete.")
        _log("")

    if not _ensure_docker(install_root):
        _pause()
        return 1

    try:
        _load_images(install_root)
        _start_services(install_root)
    except (subprocess.CalledProcessError, OSError, FileNotFoundError) as exc:
        _log(f"[ERROR] Deploy failed: {exc}")
        _pause()
        return 1

    url = f"http://127.0.0.1:{HTTP_PORT}"
    _log("")
    _log("Waiting for service...")
    if _wait_http(f"{url}/health"):
        _log(f"[OK] AI-AGENT is running: {url}")
    else:
        _log(f"[WARN] Service may still be starting. Open: {url}")

    token_file = install_root / "SETUP_TOKEN.admin.txt"
    if token_file.is_file():
        _log("")
        _log("Admin first-time setup:")
        _log(token_file.read_text(encoding="utf-8"))

    try:
        webbrowser.open(url)
    except OSError:
        pass

    _log("")
    _log("Installation complete. Keep Docker Desktop running.")
    _pause("Press Enter to close this window...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
