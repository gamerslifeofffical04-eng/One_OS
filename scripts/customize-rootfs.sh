#!/usr/bin/env bash
set -e

useradd -m -u 1000 -G wheel,audio,video,storage,network,power -s /bin/bash oneos || true
passwd -d oneos || true

mkdir -p /home/oneos/Desktop /home/oneos/.config
cp -f /usr/share/applications/calamares.desktop /home/oneos/Desktop/install-oneos.desktop || true
chmod +x /home/oneos/Desktop/install-oneos.desktop || true

# Configure Kvantum dark theme & disable Baloo indexer
mkdir -p /home/oneos/.config/Kvantum
cat <<'KV_EOF' > /home/oneos/.config/Kvantum/kvantum.kvconfig
[General]
theme=KvDark
KV_EOF

cat <<'BALOO_EOF' > /home/oneos/.config/baloofilerc
[Basic Settings]
Indexing-Enabled=false
BALOO_EOF

cat <<'ZRAM_EOF' > /etc/systemd/zram-generator.conf
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
ZRAM_EOF

chown -R oneos:oneos /home/oneos

plymouth-set-default-theme -R spinner || true
systemctl enable sddm.service
systemctl enable NetworkManager.service
systemctl enable bluetooth.service || true
systemctl enable systemd-zram-setup@zram0.service || true
