#!/usr/bin/env bash
set -euo pipefail

echo "[+] Updating packages"
sudo apt update && sudo apt upgrade -y

echo "[+] Installing Python"
sudo apt install -y python3 python3-pip

echo "[+] Installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "[+] Done"
