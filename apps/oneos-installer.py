#!/usr/bin/env python3
import glob
import os
import subprocess
import sys
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget
)


def get_disks():
    out = subprocess.check_output(
        ["lsblk", "-dpno", "NAME,SIZE,MODEL,TYPE"], text=True
    )
    disks = []
    for line in out.strip().splitlines():
        parts = line.split()
        if (
            len(parts) >= 3
            and parts[-1] == "disk"
            and "/dev/loop" not in parts[0]
            and "/dev/sr" not in parts[0]
        ):
            dev = parts[0]
            size = parts[1]
            model = " ".join(parts[2:-1]) or "Virtual Disk"
            disks.append((dev, f"{dev}  •  {size}  ({model})"))
    return disks


class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, disk, username, hostname):
        super().__init__()
        self.disk = disk
        self.username = username
        self.hostname = hostname

    def run_cmd(self, cmd, chroot=False):
        full_cmd = ["arch-chroot", "/mnt"] + cmd if chroot else cmd
        res = subprocess.run(full_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(full_cmd)}\n{res.stderr or res.stdout}"
            )

    def run(self):
        try:
            is_uefi = os.path.isdir("/sys/firmware/efi")
            part_prefix = (
                f"{self.disk}p"
                if "nvme" in self.disk or "mmcblk" in self.disk
                else self.disk
            )

            self.progress.emit(
                10, f"Formatting {self.disk} ({'UEFI' if is_uefi else 'BIOS'})..."
            )
            subprocess.run(["umount", "-R", "/mnt"], stderr=subprocess.DEVNULL)
            self.run_cmd(["wipefs", "-af", self.disk])

            if is_uefi:
                self.run_cmd(["parted", "-s", self.disk, "mklabel", "gpt"])
                self.run_cmd(
                    ["parted", "-s", self.disk, "mkpart", "EFI", "fat32", "1MiB", "513MiB"]
                )
                self.run_cmd(["parted", "-s", self.disk, "set", "1", "esp", "on"])
                self.run_cmd(
                    ["parted", "-s", self.disk, "mkpart", "ONEOS", "ext4", "513MiB", "100%"]
                )
                efi_part = f"{part_prefix}1"
                root_part = f"{part_prefix}2"
                self.run_cmd(["mkfs.fat", "-F32", efi_part])
                self.run_cmd(["mkfs.ext4", "-F", root_part])
                self.run_cmd(["mount", root_part, "/mnt"])
                os.makedirs("/mnt/boot/efi", exist_ok=True)
                self.run_cmd(["mount", efi_part, "/mnt/boot/efi"])
            else:
                self.run_cmd(["parted", "-s", self.disk, "mklabel", "msdos"])
                self.run_cmd(
                    ["parted", "-s", self.disk, "mkpart", "primary", "ext4", "1MiB", "100%"]
                )
                self.run_cmd(["parted", "-s", self.disk, "set", "1", "boot", "on"])
                root_part = f"{part_prefix}1"
                self.run_cmd(["mkfs.ext4", "-F", root_part])
                self.run_cmd(["mount", root_part, "/mnt"])

            self.progress.emit(30, "Copying OneOS system files to drive...")
            self.run_cmd([
                "rsync",
                "-aHAX",
                "--exclude=/dev/*",
                "--exclude=/proc/*",
                "--exclude=/sys/*",
                "--exclude=/tmp/*",
                "--exclude=/run/*",
                "--exclude=/mnt/*",
                "--exclude=/media/*",
                "--exclude=/lost+found",
                "--exclude=/etc/xdg/autostart/oneos-installer.desktop",
                "--exclude=/home/*/Desktop/oneos-installer.desktop",
                "/",
                "/mnt/",
            ])

            self.progress.emit(65, "Generating kernel, Plymouth & initramfs...")
            kernels = glob.glob(
                "/run/archiso/bootmnt/*/boot/x86_64/vmlinuz-linux"
            ) + glob.glob("/boot/vmlinuz-linux")
            if not kernels:
                raise RuntimeError("Could not locate vmlinuz-linux on live media.")
            self.run_cmd(["cp", "-f", kernels[0], "/mnt/boot/vmlinuz-linux"])

            with open("/mnt/etc/fstab", "w") as f:
                fstab_out = subprocess.check_output(["genfstab", "-U", "/mnt"], text=True)
                f.write(fstab_out)

            with open("/mnt/etc/hostname", "w") as f:
                f.write(f"{self.hostname}\n")

            self.run_cmd(
                [
                    "sed",
                    "-i",
                    "s/^MODULES=.*/MODULES=(vmwgfx i915 amdgpu)/",
                    "/etc/mkinitcpio.conf",
                ],
                chroot=True,
            )
            self.run_cmd(
                [
                    "sed",
                    "-i",
                    "s/^HOOKS=.*/HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)/",
                    "/etc/mkinitcpio.conf",
                ],
                chroot=True,
            )
            self.run_cmd(["mkinitcpio", "-P"], chroot=True)

            self.progress.emit(85, "Installing GRUB bootloader...")
            if is_uefi:
                self.run_cmd(
                    [
                        "grub-install",
                        "--target=x86_64-efi",
                        "--efi-directory=/boot/efi",
                        "--bootloader-id=OneOS",
                        "--recheck",
                    ],
                    chroot=True,
                )
            else:
                self.run_cmd(
                    ["grub-install", "--target=i386-pc", "--recheck", self.disk],
                    chroot=True,
                )

            self.run_cmd(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], chroot=True)

            self.progress.emit(95, "Finalizing user profile...")
            subprocess.run(
                ["arch-chroot", "/mnt", "passwd", "-d", self.username],
                stderr=subprocess.DEVNULL,
            )
            self.run_cmd(["umount", "-R", "/mnt"])

            self.progress.emit(100, "Installation complete!")
            self.finished.emit(
                True,
                "OneOS is installed! Click OK, shut down the VM, disconnect the ISO, and boot from your hard drive.",
            )
        except Exception as e:
            subprocess.run(["umount", "-R", "/mnt"], stderr=subprocess.DEV
