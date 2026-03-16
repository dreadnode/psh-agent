#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
RESOURCE_GROUP="Capabilities"
LOCATION="westus2"
VNET_NAME="c4-vnet"
SUBNET_NAME="c4-subnet"
NSG_NAME="c4-nsg"
LINUX_VM="attacker-c2"
WIN_VM="target-windows"
VM_SIZE="Standard_B2ms"  # 2 vCPU, 8 GB RAM
SSH_KEY_PATH="$HOME/.ssh/c4_attacker_rsa"
WIN_ADMIN_USER="c4admin"
WIN_PASSWORD="freedirebutzeep9*"

# ── Generate SSH key for Linux host ────────────────────────────
if [ ! -f "$SSH_KEY_PATH" ]; then
  echo "[+] Generating SSH key at $SSH_KEY_PATH"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N "" -C "c4-attacker-key"
else
  echo "[*] SSH key already exists at $SSH_KEY_PATH, reusing"
fi

# ── Create VNet and Subnet ─────────────────────────────────────
echo "[+] Creating VNet: $VNET_NAME"
az network vnet create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VNET_NAME" \
  --location "$LOCATION" \
  --address-prefix 10.0.0.0/16 \
  --subnet-name "$SUBNET_NAME" \
  --subnet-prefix 10.0.1.0/24

# ── Create NSG with rules ──────────────────────────────────────
echo "[+] Creating NSG: $NSG_NAME"
az network nsg create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$NSG_NAME" \
  --location "$LOCATION"

echo "[+] Adding NSG rules"
# SSH to Linux
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "$NSG_NAME" \
  --name AllowSSH \
  --priority 100 \
  --direction Inbound \
  --access Allow \
  --protocol Tcp \
  --destination-port-ranges 22

# RDP to Windows
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "$NSG_NAME" \
  --name AllowRDP \
  --priority 110 \
  --direction Inbound \
  --access Allow \
  --protocol Tcp \
  --destination-port-ranges 3389

# C2 beacon ports (TCP listener + HTTP checkin)
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "$NSG_NAME" \
  --name AllowC2Beacons \
  --priority 200 \
  --direction Inbound \
  --access Allow \
  --protocol Tcp \
  --destination-port-ranges 9050 9090

# Allow all traffic within subnet
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "$NSG_NAME" \
  --name AllowIntraSubnet \
  --priority 300 \
  --direction Inbound \
  --access Allow \
  --protocol "*" \
  --source-address-prefixes 10.0.1.0/24 \
  --destination-address-prefixes 10.0.1.0/24 \
  --destination-port-ranges "*"

# Associate NSG with subnet
az network vnet subnet update \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_NAME" \
  --name "$SUBNET_NAME" \
  --network-security-group "$NSG_NAME"

# ── Create Linux VM (C2 Server) ───────────────────────────────
echo "[+] Creating Linux VM: $LINUX_VM"
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$LINUX_VM" \
  --location "$LOCATION" \
  --image Canonical:ubuntu-24_04-lts:server:latest \
  --size "$VM_SIZE" \
  --vnet-name "$VNET_NAME" \
  --subnet "$SUBNET_NAME" \
  --public-ip-address "${LINUX_VM}-pip" \
  --ssh-key-values "$SSH_KEY_PATH.pub" \
  --admin-username "c4admin" \
  --os-disk-size-gb 30 \
  --output table

# ── Create Windows VM (Target) ────────────────────────────────
echo "[+] Creating Windows VM: $WIN_VM"
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WIN_VM" \
  --location "$LOCATION" \
  --image MicrosoftWindowsServer:WindowsServer:2022-datacenter-g2:latest \
  --size "$VM_SIZE" \
  --vnet-name "$VNET_NAME" \
  --subnet "$SUBNET_NAME" \
  --public-ip-address "${WIN_VM}-pip" \
  --admin-username "$WIN_ADMIN_USER" \
  --admin-password "$WIN_PASSWORD" \
  --os-disk-size-gb 128 \
  --output table

# ── Print connection info ──────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Provisioning complete"
echo "════════════════════════════════════════════════════════"

LINUX_IP=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$LINUX_VM" \
  --show-details \
  --query publicIps -o tsv)

WIN_IP=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WIN_VM" \
  --show-details \
  --query publicIps -o tsv)

LINUX_PRIVATE=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$LINUX_VM" \
  --show-details \
  --query privateIps -o tsv)

WIN_PRIVATE=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WIN_VM" \
  --show-details \
  --query privateIps -o tsv)

echo ""
echo "  Linux (C2):   ssh -i $SSH_KEY_PATH c4admin@$LINUX_IP"
echo "  Windows:      RDP to $WIN_IP  (user: $WIN_ADMIN_USER)"
echo ""
echo "  Private IPs:  $LINUX_VM → $LINUX_PRIVATE"
echo "                $WIN_VM  → $WIN_PRIVATE"
echo ""
echo "  C2 ports:     9050 (HTTP), 9090 (TCP) open on NSG"
echo "  SSH key:      $SSH_KEY_PATH"
echo "════════════════════════════════════════════════════════"
