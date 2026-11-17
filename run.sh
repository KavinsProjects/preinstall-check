#!/usr/bin/env bash
# Hardware Checker launcher (v0.1, apt only).
# Installs python3 and the optional tools if missing, then runs the checker.
#
# Usage:
#   ./run.sh [--no-install] [checker options]
#   ./run.sh --json report.json
#
# --no-install   skip installing packages; just run with what is available.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/hardware_checker.py"

INSTALL=1
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--no-install" ]; then
        INSTALL=0
    else
        ARGS+=("$arg")
    fi
done

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Error: apt-get not found. v0.1 supports apt-based distributions only"
    echo "(Ubuntu, Linux Mint, Debian). Other package managers are planned."
    exit 1
fi

# Use sudo only when not already root.
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    SUDO=""
    INSTALL=0
    echo "Note: not root and sudo is unavailable; skipping package installs."
fi

# command -> apt package
declare -A PACKAGES=(
    [python3]="python3"
    [lspci]="pciutils"
    [lsusb]="usbutils"
    [mokutil]="mokutil"
)

MISSING=()
for cmd in "${!PACKAGES[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        MISSING+=("${PACKAGES[$cmd]}")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ] && [ "$INSTALL" -eq 1 ]; then
    echo "Missing packages: ${MISSING[*]}"
    echo "Installing with apt..."
    $SUDO apt-get update -qq
    if ! $SUDO apt-get install -y -qq "${MISSING[@]}"; then
        echo "Warning: could not install some packages. Continuing anyway."
    fi
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but could not be installed."
    echo "Install it manually: sudo apt install python3"
    exit 1
fi

exec python3 "$CHECKER" ${ARGS[@]+"${ARGS[@]}"}
