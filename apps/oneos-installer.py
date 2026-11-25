#!/usr/bin/env python3
import os
import subprocess
import sys
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget
)

def get_disks():
    out = subprocess.check_output(
        ["lsblk", "-dpno", "NAME,SIZE,MODEL,TYPE"], text=True
    )
    disks = []
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == "disk" and "/dev/loop" not in parts[0] and "/dev/sr" not in parts[0]:
            dev = parts[0]
            size = parts[1]
            model = " ".join(parts[2:-1]) or "Virtual Disk"
            disks.append((dev, f"{dev} ({size} - {model})"))
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
            raise RuntimeError(f"Command failed: {' '.join(full_cmd)}\n{res.stderr or res.stdout}")

    def run(self):
        try:
            is_uefi = os.path.isdir("/sys/firmware/efi")
            part_prefix = f"{self.disk}p" if "nvme" in self.disk or "mmcblk" in self.disk else self.disk

            self.progress.emit(10, f"Partitioning {self.disk} ({'UEFI' if is_uefi else 'BIOS'})...")
            subprocess.run(["umount", "-R", "/mnt"], stderr=subprocess.DEVNULL)
            self.run_cmd(["wipefs", "-af", self.disk])

            if is_uefi:
                self.run_cmd(["parted", "-s", self.disk, "mklabel", "gpt"])
                self.run_cmd(["parted", "-s", self.disk, "mkpart", "EFI", "fat32", "1MiB", "513MiB"])
                self.run_cmd(["parted", "-s", self.disk, "set", "1", "esp", "on"])
                self.run_cmd(["parted", "-s", self.disk, "mkpart", "ONEOS", "ext4", "513MiB", "100%"])
                efi_part = f"{part_prefix}1"
                root_part = f"{part_prefix}2"
                self.run_cmd(["mkfs.fat", "-F32", efi_part])
                self.run_cmd(["mkfs.ext4", "-F", root_part])
                self.run_cmd(["mount", root_part, "/mnt"])
                os.makedirs("/mnt/boot/efi", exist_ok=True)
                self.run_cmd(["mount", efi_part, "/mnt/boot/efi"])
            else:
                self.run_cmd(["parted", "-s", self.disk, "mklabel", "msdos"])
                self.run_cmd(["parted", "-s", self.disk, "mkpart", "primary", "ext4", "1MiB", "100%"])
                self.run_cmd(["parted", "-s", self.disk, "set", "1", "boot", "on"])
                root_part = f"{part_prefix}1"
                self.run_cmd(["mkfs.ext4", "-F", root_part])
                self.run_cmd(["mount", root_part, "/mnt"])

            self.progress.emit(30, "Copying OneOS system files to disk...")
            self.run_cmd([
                "rsync", "-aHAX", "--info=progress2",
                "--exclude=/dev/*", "--exclude=/proc/*", "--exclude=/sys/*",
                "--exclude=/tmp/*", "--exclude=/run/*", "--exclude=/mnt/*",
                "--exclude=/media/*", "--exclude=/lost+found",
                "--exclude=/etc/xdg/autostart/oneos-installer.desktop",
                "/", "/mnt/"
            ])

            self.progress.emit(65, "Configuring kernel, initramfs, and fstab...")
            self.run_cmd(["cp", "-f", "/run/archiso/bootmnt/arch/boot/x86_64/vmlinuz-linux", "/mnt/boot/vmlinuz-linux"])
            with open("/mnt/etc/fstab", "w") as f:
                fstab_out = subprocess.check_output(["genfstab", "-U", "/mnt"], text=True)
                f.write(fstab_out)

            with open("/mnt/etc/hostname", "w") as f:
                f.write(f"{self.hostname}\n")

            self.run_cmd([
                "sed", "-i",
                "s/^HOOKS=.*/HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)/",
                "/etc/mkinitcpio.conf"
            ], chroot=True)
            self.run_cmd(["mkinitcpio", "-P"], chroot=True)

            self.progress.emit(85, "Installing GRUB bootloader...")
            if is_uefi:
                self.run_cmd([
                    "grub-install", "--target=x86_64-efi",
                    "--efi-directory=/boot/efi", "--bootloader-id=OneOS", "--recheck"
                ], chroot=True)
            else:
                self.run_cmd(["grub-install", "--target=i386-pc", "--recheck", self.disk], chroot=True)

            self.run_cmd(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], chroot=True)

            self.progress.emit(95, "Finalizing zero-password user account...")
            subprocess.run(["arch-chroot", "/mnt", "passwd", "-d", self.username], stderr=subprocess.DEVNULL)
            self.run_cmd(["umount", "-R", "/mnt"])

            self.progress.emit(100, "Installation complete!")
            self.finished.emit(True, "OneOS has been installed cleanly. Shut down, disconnect the ISO, and boot from your disk!")
        except Exception as e:
            subprocess.run(["umount", "-R", "/mnt"], stderr=subprocess.DEVNULL)
            self.finished.emit(False, str(e))

class OneOSInstaller(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Install OneOS")
        self.setFixedSize(480, 320)
        self.setStyleSheet("""
            QWidget { background-color: #14161b; color: #f0f2f5; font-family: Inter, sans-serif; font-size: 13px; }
            QComboBox, QLineEdit { background-color: #1e222a; border: 1px solid #323846; border-radius: 6px; padding: 6px; color: #ffffff; }
            QPushButton { background-color: #3b82f6; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; }
            QPushButton:disabled { background-color: #2d333f; color: #7c8494; }
            QProgressBar { background-color: #1e222a; border-radius: 6px; text-align: center; height: 22px; }
            QProgressBar::chunk { background-color: #3b82f6; border-radius: 6px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Install OneOS to Disk")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        form = QFormLayout()
        self.disk_box = QComboBox()
        for dev, label in get_disks():
            self.disk_box.addItem(label, dev)
        form.addRow("Target Drive:", self.disk_box)

        self.user_edit = QLineEdit("oneos")
        self.user_edit.setReadOnly(True)
        form.addRow("User (Zero-Password):", self.user_edit)

        self.host_edit = QLineEdit("oneos-pc")
        form.addRow("Computer Name:", self.host_edit)
        layout.addLayout(form)

        self.status_label = QLabel("Warning: Selected drive will be erased.")
        self.status_label.setStyleSheet("color: #9ca3af;")
        layout.addWidget(self.status_label)

        self.bar = QProgressBar()
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        self.install_btn = QPushButton("Erase Disk && Install OneOS")
        self.install_btn.clicked.connect(self.start_install)
        layout.addWidget(self.install_btn)

    def start_install(self):
        disk = self.disk_box.currentData()
        if not disk:
            QMessageBox.critical(self, "No Disk", "No target hard drive detected.")
            return
        reply = QMessageBox.question(
            self, "Confirm Erase",
            f"All data on {disk} will be erased and replaced with OneOS. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.install_btn.setEnabled(False)
        self.disk_box.setEnabled(False)
        self.worker = InstallWorker(disk, self.user_edit.text(), self.host_edit.text().strip() or "oneos-pc")
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, val, msg):
        self.bar.setValue(val)
        self.status_label.setText(msg)

    def on_finished(self, ok, msg):
        self.install_btn.setEnabled(True)
        self.disk_box.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Install Error", msg)

if __name__ == "__main__":
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "-E", sys.executable] + sys.argv)
    app = QApplication(sys.argv)
    win = OneOSInstaller()
    win.show()
    sys.exit(app.exec())
