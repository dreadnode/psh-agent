#!/usr/bin/env bash
set -euo pipefail

echo "[+] Updating packages"
sudo apt update && sudo apt upgrade -y

echo "[+] Installing Python"
sudo apt install -y python3 python3-pip

echo "[+] Installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "[+] Installing Camoufox/Firefox dependencies (GTK3, X11, audio)"
sudo apt install -y libgtk-3-0 libdbus-glib-1-2 libasound2t64 libx11-xcb1 \
  libxcomposite1 libxdamage1 libxrandr2 libxss1 libxtst6 libatk-bridge2.0-0

echo "[+] Done"
