#!/usr/bin/env bash
set -euo pipefail

ONEOS_VERSION="${ONEOS_VERSION:-1.0.0}"
REPO_DIR="/workspace"
PROFILE_DIR="/build/oneos-profile"
WORK_DIR="/build/work"
OUT_DIR="${REPO_DIR}/out"

pacman-key --init
pacman-key --populate archlinux
pacman -Syu --noconfirm archiso git base-devel

rm -rf "${PROFILE_DIR}" "${WORK_DIR}" "${OUT_DIR}"
mkdir -p "${OUT_DIR}"
cp -r /usr/share/archiso/configs/releng "${PROFILE_DIR}"

# 1. ISO Metadata
sed -i 's/^iso_name=.*/iso_name="OneOS"/' "${PROFILE_DIR}/profiledef.sh"
sed -i "s/^iso_version=.*/iso_version=\"v${ONEOS_VERSION}\"/" "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_label=.*/iso_label="ONEOS_LIVE"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_publisher=.*/iso_publisher="OneOS Project"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_application=.*/iso_application="OneOS Live\/Install Media"/' "${PROFILE_DIR}/profiledef.sh"

# 2. Packages (Plasma 6 X11, Plymouth, Kvantum, Calamares, PyQt6 WebEngine)
cat <<'PKGS_EOF' >> "${PROFILE_DIR}/packages.x86_64"
xorg-server
xorg-xinit
plasma-desktop
plasma-workspace
plasma-x11-session
kwin
sddm
breeze
breeze-gtk
kde-gtk-config
kvantum
systemsettings
konsole
dolphin
ark
spectacle
plasma-nm
plasma-pa
bluedevil
powerdevil
kscreen
discover
flatpak
papirus-icon-theme
ttf-inter
noto-fonts
noto-fonts-emoji
plymouth
linux-firmware
intel-ucode
networkmanager
zram-generator
pipewire
pipewire-pulse
wireplumber
calamares
squashfs-tools
rsync
grub
efibootmgr
os-prober
dosfstools
mtools
python
python-pyqt6
python-pyqt6-webengine
python-requests
python-pillow
xclip
fastfetch
vlc
PKGS_EOF

AIROOTFS="${PROFILE_DIR}/airootfs"
mkdir -p \
  "${AIROOTFS}/etc/sddm.conf.d" \
  "${AIROOTFS}/etc/xdg/autostart" \
  "${AIROOTFS}/etc/calamares/modules" \
  "${AIROOTFS}/etc/sudoers.d" \
  "${AIROOTFS}/etc/plymouth" \
  "${AIROOTFS}/etc/mkinitcpio.conf.d" \
  "${AIROOTFS}/usr/local/bin"

# 3. Copy Modular Apps & Configs from Repo
cp -f "${REPO_DIR}/apps/oneos-gemini-pill.py" "${AIROOTFS}/usr/local/bin/oneos-gemini-assistant.py"
cp -f "${REPO_DIR}/apps/oneos-boot-splash.py" "${AIROOTFS}/usr/local/bin/oneos-boot-splash"
cp -f "${REPO_DIR}/apps/oneos-ota-updater.py" "${AIROOTFS}/usr/local/bin/oneos-ota-updater"
chmod 0755 "${AIROOTFS}/usr/local/bin/"oneos-*

cp -f "${REPO_DIR}/configs/kdeglobals" "${AIROOTFS}/etc/xdg/kdeglobals"
cp -f "${REPO_DIR}/configs/plymouthd.conf" "${AIROOTFS}/etc/plymouth/plymouthd.conf"
cp -f "${REPO_DIR}/configs/calamares/settings.conf" "${AIROOTFS}/etc/calamares/settings.conf"
cp -f "${REPO_DIR}/configs/calamares/unpackfs.conf" "${AIROOTFS}/etc/calamares/modules/unpackfs.conf"
cp -f "${REPO_DIR}/configs/calamares/bootloader.conf" "${AIROOTFS}/etc/calamares/modules/bootloader.conf"
cp -f "${REPO_DIR}/scripts/customize-rootfs.sh" "${AIROOTFS}/root/customize_airootfs.sh"
chmod 0755 "${AIROOTFS}/root/customize_airootfs.sh"

# 4. Enable Plymouth Hook in mkinitcpio & Silent Kernel Boot Flags
cat <<'MKINIT_EOF' > "${AIROOTFS}/etc/mkinitcpio.conf.d/oneos-plymouth.conf"
HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)
MKINIT_EOF

sed -i 's/quiet/quiet splash loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0/g' \
  "${PROFILE_DIR}/efiboot/loader/entries/"*.conf \
  "${PROFILE_DIR}/syslinux/"*.cfg 2>/dev/null || true

# 5. OS Identity & Autostart Entries
cat <<'OS_REL_EOF' > "${AIROOTFS}/etc/os-release"
NAME="OneOS"
PRETTY_NAME="OneOS"
ID=oneos
ID_LIKE=arch
BUILD_ID=rolling
HOME_URL="https://github.com/vga4400x4400-blip/OneOS"
LOGO=start-here-kde
OS_REL_EOF
echo "ONEOS_VERSION=${ONEOS_VERSION}" > "${AIROOTFS}/etc/oneos-release"

cat <<'SDDM_EOF' > "${AIROOTFS}/etc/sddm.conf.d/10-oneos.conf"
[General]
DisplayServer=x11

[Autologin]
User=oneos
Session=plasmax11.desktop
Relogin=false

[Theme]
Current=breeze
SDDM_EOF

echo "%wheel ALL=(ALL:ALL) NOPASSWD: ALL" > "${AIROOTFS}/etc/sudoers.d/oneos-nopasswd"
chmod 0440 "${AIROOTFS}/etc/sudoers.d/oneos-nopasswd"

cat <<'SPLASH_DESK' > "${AIROOTFS}/etc/xdg/autostart/oneos-boot-splash.desktop"
[Desktop Entry]
Type=Application
Name=OneOS Boot Splash
Exec=/usr/local/bin/oneos-boot-splash
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=0
SPLASH_DESK

cat <<'PILL_DESK' > "${AIROOTFS}/etc/xdg/autostart/oneos-gemini-pill.desktop"
[Desktop Entry]
Type=Application
Name=OneOS Gemini Corner Pill
Exec=/bin/bash -c 'sleep 3 && /usr/local/bin/oneos-gemini-assistant.py'
Terminal=false
NoDisplay=true
X-KDE-autostart-after=panel
PILL_DESK

# 6. Build ISO
mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE_DIR}"
