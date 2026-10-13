#!/bin/bash
# ==============================================================================
# AUTOMATED DEPLOYMENT SCRIPT: RASPBERRY PI ZERO GATEWAY
# Pushes code, enables SPI, installs dependencies, and starts background service
# ==============================================================================

set -e

PI_HOST="fridgemaster.local"
PI_USER="adamchristmas"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Target: ${PI_USER}@${PI_HOST} ==="

echo "[1/4] Transferring files to Raspberry Pi..."
scp "${PROJECT_DIR}/lora_bridge.py" "${PI_USER}@${PI_HOST}:/home/${PI_USER}/lora_bridge.py"
scp "${PROJECT_DIR}/lora-bridge.service" "${PI_USER}@${PI_HOST}:/tmp/lora-bridge.service"

echo "[2/4] Configuring hardware bus and installing packages..."
ssh "${PI_USER}@${PI_HOST}" << 'REMOTECOMMANDS'
    # Enable hardware SPI bus
    sudo raspi-config nonint do_spi 0

    # Refresh package index and install required Python hardware libraries
    sudo apt update
    sudo apt install -y python3-pip python3-spidev python3-rpi.gpio

    # Install Python dependencies
    pip3 install requests pyLora --break-system-packages

    # Move service definition into place and enable at boot
    sudo mv /tmp/lora-bridge.service /etc/systemd/system/lora-bridge.service
    sudo systemctl daemon-reload
    sudo systemctl enable lora-bridge.service
    sudo systemctl restart lora-bridge.service
REMOTECOMMANDS

echo "[3/4] Checking service status on Pi..."
ssh "${PI_USER}@${PI_HOST}" "sudo systemctl status lora-bridge.service --no-pager"

echo "[4/4] Deployment complete. Gateway service is active and listening."
