#!/usr/bin/env bash
set -euo pipefail

ONEOS_VERSION="${ONEOS_VERSION:-1.0.0}"
REPO_DIR="/workspace"
PROFILE_DIR="/build/oneos-profile"
WORK_DIR="/build/work"
OUT_DIR="${REPO_DIR}/out"

pacman-key --init
pacman-key --populate archlinux
pacman -Syu --noconfirm archiso git

rm -rf /build "${OUT_DIR}"
mkdir -p /build "${OUT_DIR}"

# 1. Setup ArchISO Profile
cp -r /usr/share/archiso/configs/releng "${PROFILE_DIR}"

# 2. ISO Metadata & Explicit Executable Permissions
sed -i 's/^iso_name=.*/iso_name="OneOS"/' "${PROFILE_DIR}/profiledef.sh"
sed -i "s/^iso_version=.*/iso_version=\"v${ONEOS_VERSION}\"/" "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_label=.*/iso_label="ONEOS_LIVE"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_publisher=.*/iso_publisher="OneOS Project"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_application=.*/iso_application="OneOS Live\/Install Media"/' "${PROFILE_DIR}/profiledef.sh"

sed -i '/^file_permissions=(/a \  ["/usr/local/bin/oneos-installer"]="0:0:755"\n  ["/usr/local/bin/oneos-gemini-assistant.py"]="0:0:755"\n  ["/usr/local/bin/oneos-boot-splash"]="0:0:755"\n  ["/usr/local/bin/oneos-ota-updater"]="0:0:755"\n  ["/usr/local/bin/oneos-trust-desktop"]="0:0:755"' "${PROFILE_DIR}/profiledef.sh"

# 3. Packages
cat <<'PKGS_EOF' >> "${PROFILE_DIR}/packages.x86_64"
xorg-server
xorg-xinit
plasma-desktop
plasma-workspace
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
inter-font
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
squashfs-tools
rsync
parted
arch-install-scripts
grub
efibootmgr
os-prober
dosfstools
mtools
glib2
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
  "${AIROOTFS}/etc/sudoers.d" \
  "${AIROOTFS}/etc/plymouth" \
  "${AIROOTFS}/etc/skel/Desktop" \
  "${AIROOTFS}/usr/local/bin" \
  "${AIROOTFS}/usr/share/applications"

# 4. Copy OneOS Apps & Configs from Repo
cp -f "${REPO_DIR}/apps/oneos-installer.py" "${AIROOTFS}/usr/local/bin/oneos-installer"
cp -f "${REPO_DIR}/apps/oneos-gemini-pill.py" "${AIROOTFS}/usr/local/bin/oneos-gemini-assistant.py"
cp -f "${REPO_DIR}/apps/oneos-boot-splash.py" "${AIROOTFS}/usr/local/bin/oneos-boot-splash"
cp -f "${REPO_DIR}/apps/oneos-ota-updater.py" "${AIROOTFS}/usr/local/bin/oneos-ota-updater"
chmod 0755 "${AIROOTFS}/usr/local/bin/"oneos-*

cp -f "${REPO_DIR}/configs/kdeglobals" "${AIROOTFS}/etc/xdg/kdeglobals"
cp -f "${REPO_DIR}/scripts/customize-rootfs.sh" "${AIROOTFS}/root/customize_airootfs.sh"
chmod 0755 "${AIROOTFS}/root/customize_airootfs.sh"

# 5. Early KMS for VMware/GPU + Plymouth Boot Splash
sed -i 's/^MODULES=.*/MODULES=(vmwgfx i915 amdgpu)/' "${AIROOTFS}/etc/mkinitcpio.conf" 2>/dev/null || true
sed -i 's/\budev\b/udev plymouth/' "${AIROOTFS}/etc/mkinitcpio.conf.d/archiso.conf" 2>/dev/null || \
  sed -i 's/\budev\b/udev plymouth/' "${AIROOTFS}/etc/mkinitcpio.conf" 2>/dev/null || true

cat <<'PLY_CONF' > "${AIROOTFS}/etc/plymouth/plymouthd.conf"
[Daemon]
Theme=spinner
ShowDelay=0
DeviceTimeout=5
PLY_CONF

for entry in "${PROFILE_DIR}/efiboot/loader/entries/"*.conf "${PROFILE_DIR}/syslinux/"*.cfg; do
  if [ -f "$entry" ]; then
    sed -i 's/\bquiet\b/quiet splash loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0/g' "$entry"
    grep -q "splash" "$entry" || sed -i '/^options / s/$/ quiet splash loglevel=3 vt.global_cursor_default=0/' "$entry"
    grep -q "splash" "$entry" || sed -i '/^\s*APPEND / s/$/ quiet splash loglevel=3 vt.global_cursor_default=0/' "$entry"
  fi
done

# 6. OS Identity, Zero-Password Sudo & Trusted Autostart Entries
cat <<'OS_REL_EOF' > "${AIROOTFS}/etc/os-release"
NAME="OneOS"
PRETTY_NAME="OneOS"
ID=oneos
ID_LIKE=arch
BUILD_ID=rolling
HOME_URL="https://github.com/gamerslifeofffical04-eng/One_OS"
LOGO=start-here-kde
OS_REL_EOF
echo "ONEOS_VERSION=${ONEOS_VERSION}" > "${AIROOTFS}/etc/oneos-release"

cat <<'SDDM_EOF' > "${AIROOTFS}/etc/sddm.conf.d/10-oneos.conf"
[Autologin]
User=oneos
Session=plasma.desktop
Relogin=false

[Theme]
Current=breeze
SDDM_EOF

cat <<'SUDO_EOF' > "${AIROOTFS}/etc/sudoers.d/oneos-nopasswd"
Defaults env_keep += "DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS"
%wheel ALL=(ALL:ALL) NOPASSWD: ALL
SUDO_EOF
chmod 0440 "${AIROOTFS}/etc/sudoers.d/oneos-nopasswd"

# Helper script that marks Desktop icons trusted in KDE Plasma 6
cat <<'TRUST_SH' > "${AIROOTFS}/usr/local/bin/oneos-trust-desktop"
#!/usr/bin/env bash
sleep 2
if [ -f "$HOME/Desktop/oneos-installer.desktop" ]; then
  chmod +x "$HOME/Desktop/oneos-installer.desktop"
  gio set "$HOME/Desktop/oneos-installer.desktop" metadata::trusted true 2>/dev/null || true
fi
TRUST_SH
chmod 0755 "${AIROOTFS}/usr/local/bin/oneos-trust-desktop"

cat <<'INSTALL_DESK' > "${AIROOTFS}/usr/share/applications/oneos-installer.desktop"
[Desktop Entry]
Type=Application
Name=Install OneOS
Comment=Install OneOS to your hard drive
Exec=/usr/local/bin/oneos-installer
Icon=system-software-install
Terminal=false
Categories=System;
INSTALL_DESK
chmod 0755 "${AIROOTFS}/usr/share/applications/oneos-installer.desktop"

cp -f "${AIROOTFS}/usr/share/applications/oneos-installer.desktop" "${AIROOTFS}/etc/skel/Desktop/oneos-installer.desktop"
chmod 0755 "${AIROOTFS}/etc/skel/Desktop/oneos-installer.desktop"

# OneOS PyQt6 Boot/Welcome Splash
cat <<'SPLASH_DESK' > "${AIROOTFS}/etc/xdg/autostart/oneos-boot-splash.desktop"
[Desktop Entry]
Type=Application
Name=OneOS Boot Splash
Exec=/usr/local/bin/oneos-boot-splash
Icon=start-here-kde
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=Initialization
SPLASH_DESK

# Auto-trust desktop shortcut + open OneOS Setup automatically on live boot
cat <<'INSTALL_AUTO' > "${AIROOTFS}/etc/xdg/autostart/oneos-installer.desktop"
[Desktop Entry]
Type=Application
Name=Install OneOS
Exec=/bin/bash -c '/usr/local/bin/oneos-trust-desktop && sleep 1 && /usr/local/bin/oneos-installer'
Icon=system-software-install
Terminal=false
X-KDE-autostart-phase=Application
INSTALL_AUTO

# Auto-launch Gemini Corner Pill on both Live and Installed systems
cat <<'PILL_DESK' > "${AIROOTFS}/etc/xdg/autostart/oneos-gemini-pill.desktop"
[Desktop Entry]
Type=Application
Name=OneOS Gemini Corner Pill
Exec=/bin/bash -c 'sleep 3 && /usr/local/bin/oneos-gemini-assistant.py'
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=Application
PILL_DESK

# 7. Build ISO & Fix Host Output Permissions
mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE_DIR}"
chmod -R 777 "${OUT_DIR}"
