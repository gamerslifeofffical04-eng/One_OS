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

# 1. Setup ArchISO Profile & Enable [multilib] for Windows App Support
cp -r /usr/share/archiso/configs/releng "${PROFILE_DIR}"

sed -i '/^[options]/a Architecture = x86_64' "${PROFILE_DIR}/pacman.conf"

cat <<'MULTILIB_EOF' >> "${PROFILE_DIR}/pacman.conf"

[multilib]
Include = /etc/pacman.d/mirrorlist
MULTILIB_EOF

# 2. ISO Metadata & Explicit Executable Permissions
sed -i 's/^iso_name=.*/iso_name="OneOS"/' "${PROFILE_DIR}/profiledef.sh"
sed -i "s/^iso_version=.*/iso_version=\"v${ONEOS_VERSION}\"/" "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_label=.*/iso_label="ONEOS_LIVE"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_publisher=.*/iso_publisher="OneOS Project"/' "${PROFILE_DIR}/profiledef.sh"
sed -i 's/^iso_application=.*/iso_application="OneOS Live\/Install Media"/' "${PROFILE_DIR}/profiledef.sh"

sed -i '/^file_permissions=(/a \  ["/usr/local/bin/oneos-installer"]="0:0:755"\n  ["/usr/local/bin/oneos-gemini-assistant.py"]="0:0:755"\n  ["/usr/local/bin/oneos-boot-splash"]="0:0:755"\n  ["/usr/local/bin/oneos-ota-updater"]="0:0:755"\n  ["/usr/local/bin/oneos-trust-desktop"]="0:0:755"' "${PROFILE_DIR}/profiledef.sh"

# 3. Packages (Plasma 6, Core Utilities, Plymouth, Firmware & Wine Support)
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
amd-ucode
open-vm-tools
mesa
vulkan-intel
vulkan-radeon
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
wine-staging
wine-mono
wine-gecko
winetricks
lib32-mesa
lib32-vulkan-icd-loader
lib32-pipewire
PKGS_EOF

AIROOTFS="${PROFILE_DIR}/airootfs"
mkdir -p \
  "${AIROOTFS}/etc/sddm.conf.d" \
  "${AIROOTFS}/etc/xdg/autostart" \
  "${AIROOTFS}/etc/sudoers.d" \
  "${AIROOTFS}/etc/plymouth" \
  "${AIROOTFS}/etc/systemd/sleep.conf.d" \
  "${AIROOTFS}/etc/skel/.config" \
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

sed -i '/^[options]/a Architecture = x86_64' "${AIROOTFS}/etc/pacman.conf"

cat <<'TARGET_MULTILIB' >> "${AIROOTFS}/etc/pacman.conf"

[multilib]
Include = /etc/pacman.d/mirrorlist
TARGET_MULTILIB

# 5. Universal Storage, GPU, Network & Input Drivers + Plymouth Boot Splash
ALL_MODULES="ahci sd_mod sr_mod nvme nvme_core vmw_pvscsi mptspi mpt3sas virtio_blk virtio_scsi virtio_pci hv_storvsc uas usb_storage vmwgfx i915 xe amdgpu radeon nouveau virtio_gpu bochs qxl e1000 e1000e vmxnet3 r8169 igc iwlwifi virtio_net usbhid hid_generic xhci_pci ehci_pci"

sed -i "s/^MODULES=.*/MODULES=(${ALL_MODULES})/" "${AIROOTFS}/etc/mkinitcpio.conf" 2>/dev/null || true
sed -i 's/\budev\b/udev plymouth/' "${AIROOTFS}/etc/mkinitcpio.conf.d/archiso.conf" 2>/dev/null || \
  sed -i 's/\budev\b/udev plymouth/' "${AIROOTFS}/etc/mkinitcpio.conf" 2>/dev/null || true

cat <<'PLY_CONF' > "${AIROOTFS}/etc/plymouth/plymouthd.conf"
[Daemon]
Theme=spinner
ShowDelay=0
DeviceTimeout=5
PLY_CONF

for entry in "${PROFILE_DIR}/efiboot/loader/entries/"*.conf "${
