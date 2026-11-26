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

            self.progress.emit(65, "Generating kernel & initramfs...")
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
            subprocess.run(["umount", "-R", "/mnt"], stderr=subprocess.DEVNULL)
            self.finished.emit(False, str(e))


class OneOSInstaller(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OneOS Setup")
        self.setFixedSize(540, 430)
        self.setStyleSheet("""
            QWidget {
                background-color: #0d1017;
                color: #f3f4f6;
                font-family: 'Inter', 'Noto Sans', sans-serif;
                font-size: 13px;
            }
            QFrame#Card {
                background-color: #151a24;
                border: 1px solid #232a3b;
                border-radius: 14px;
            }
            QLabel#Badge {
                background-color: rgba(59, 130, 246, 0.16);
                color: #60a5fa;
                border: 1px solid rgba(59, 130, 246, 0.35);
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#Title {
                font-size: 22px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#Subtitle {
                color: #9ca3af;
                font-size: 13px;
            }
            QLabel#FieldLabel {
                color: #cbd5e1;
                font-weight: 600;
                font-size: 12px;
            }
            QComboBox, QLineEdit {
                background-color: #0f131b;
                border: 1px solid #2b3448;
                border-radius: 8px;
                padding: 9px 12px;
                color: #ffffff;
                font-size: 13px;
            }
            QComboBox:focus, QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QPushButton#InstallBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 12px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#InstallBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #6366f1);
            }
            QPushButton#InstallBtn:disabled {
                background: #1f2633;
                color: #6b7280;
            }
            QProgressBar {
                background-color: #0f131b;
                border: 1px solid #232a3b;
                border-radius: 7px;
                text-align: center;
                color: #e5e7eb;
                font-weight: 600;
                height: 16px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #8b5cf6);
                border-radius: 6px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        # Header
        header_top = QHBoxLayout()
        badge = QLabel("ONEOS LIVE INSTALLER")
        badge.setObjectName("Badge")
        header_top.addWidget(badge)
        header_top.addStretch()
        mode_lbl = QLabel("UEFI" if os.path.isdir("/sys/firmware/efi") else "Legacy BIOS")
        mode_lbl.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        header_top.addWidget(mode_lbl)
        root.addLayout(header_top)

        title = QLabel("Install OneOS to Your Drive")
        title.setObjectName("Title")
        root.addWidget(title)

        sub = QLabel("Fast, clean installation with Gemini AI assistant and Plasma 6 preconfigured.")
        sub.setObjectName("Subtitle")
        root.addWidget(sub)

        # Card
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(12)

        lbl_disk = QLabel("TARGET STORAGE DRIVE")
        lbl_disk.setObjectName("FieldLabel")
        card_layout.addWidget(lbl_disk)

        self.disk_box = QComboBox()
        for dev, label in get_disks():
            self.disk_box.addItem(label, dev)
        card_layout.addWidget(self.disk_box)

        row = QHBoxLayout()
        row.setSpacing(12)

        col1 = QVBoxLayout()
        lbl_user = QLabel("ACCOUNT (AUTO-LOGIN)")
        lbl_user.setObjectName("FieldLabel")
        self.user_edit = QLineEdit("oneos")
        self.user_edit.setReadOnly(True)
        col1.addWidget(lbl_user)
        col1.addWidget(self.user_edit)

        col2 = QVBoxLayout()
        lbl_host = QLabel("DEVICE NAME")
        lbl_host.setObjectName("FieldLabel")
        self.host_edit = QLineEdit("oneos-pc")
        col2.addWidget(lbl_host)
        col2.addWidget(self.host_edit)

        row.addLayout(col1)
        row.addLayout(col2)
        card_layout.addLayout(row)

        root.addWidget(card)

        # Progress & Status
        self.status_label = QLabel("Ready to install. Selected drive will be formatted.")
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(self.status_label)

        self.bar = QProgressBar()
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        root.addWidget(self.bar)

        self.install_btn = QPushButton("Erase Drive && Install OneOS")
        self.install_btn.setObjectName("InstallBtn")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self.start_
