#!/usr/bin/env python3
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
import requests
from PyQt6.QtWidgets import QApplication, QMessageBox

REPO = "vga4400x4400-blip/OneOS"
RELEASE_FILE = Path("/etc/oneos-release")


def get_local_version() -> str:
    if RELEASE_FILE.exists():
        for line in RELEASE_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("ONEOS_VERSION="):
                return line.split("=", 1)[1].strip().strip('"').lstrip("v")
    return "1.0.0"


def check_and_apply(silent: bool = False):
    app = QApplication(sys.argv)
    local_ver = get_local_version()

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            if not silent:
                QMessageBox.warning(None, "OneOS Update", "Could not reach GitHub update server.")
            return
        data = resp.json()
    except Exception as exc:
        if not silent:
            QMessageBox.warning(None, "OneOS Update", f"Network check failed:\n{exc}")
        return

    latest_tag = data.get("tag_name", "").lstrip("v")
    if not latest_tag or latest_tag == local_ver:
        if not silent:
            QMessageBox.information(None, "OneOS is Up to Date", f"You are running the latest version (v{local_ver}).")
        return

    patch_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == "oneos-ota-patch.tar.gz":
            patch_url = asset.get("browser_download_url")
            break

    reply = QMessageBox.question(
        None,
        f"OneOS Update Available (v{latest_tag})",
        f"A new OneOS update is available!\n\n"
        f"Current version: v{local_ver}\n"
        f"New version: v{latest_tag}\n\n"
        f"Install OneOS OTA update and system packages now?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    patch_cmd = ""
    with tempfile.TemporaryDirectory() as tmpdir:
        if patch_url:
            archive_path = os.path.join(tmpdir, "oneos-ota-patch.tar.gz")
            with requests.get(patch_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(archive_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

            extract_dir = os.path.join(tmpdir, "unpacked")
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)
            patch_cmd = f"cp -rf {extract_dir}/* / && chmod 0755 /usr/local/bin/oneos-* && "

        apply_cmd = (
            f"{patch_cmd}"
            f"echo 'ONEOS_VERSION={latest_tag}' > /etc/oneos-release && "
            f"pacman -Syu --noconfirm && "
            f"(command -v flatpak >/dev/null && flatpak update -y || true)"
        )
        subprocess.run(["sudo", "bash", "-c", apply_cmd], check=False)

    QMessageBox.information(
        None,
        "OneOS Updated",
        f"OneOS has been updated to v{latest_tag}! Log out and back in (or reboot) to apply all UI changes.",
    )


if __name__ == "__main__":
    check_and_apply(silent=("--silent" in sys.argv))
