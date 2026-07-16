#!/usr/bin/env bash
# =============================================================================
# linux-macvlan-setup.sh — Prepare a Linux host for WebNetLab macvlan mode
#
# What this script does:
#   1. Detects the default outbound NIC (used as macvlan parent)
#   2. Enables promiscuous mode on that NIC
#   3. Adds a routing rule so the Linux host itself can reach macvlan containers
#      (by default the host cannot communicate with its own macvlan children —
#       this is a Linux kernel limitation; the fix is a macvlan shim interface)
#   4. Persists promiscuous mode via systemd-networkd or /etc/rc.local
#
# Usage:
#   sudo bash infra/linux-macvlan-setup.sh [PARENT_IFACE] [SUBNET] [GATEWAY]
#
#   PARENT_IFACE  Physical NIC to use as macvlan parent (default: auto-detect)
#   SUBNET        Subnet you will assign to simulated devices (default: 192.168.100.0/24)
#   GATEWAY       Gateway IP for that subnet (default: 192.168.100.1)
#
# Example:
#   sudo bash infra/linux-macvlan-setup.sh eth0 192.168.100.0/24 192.168.100.1
#
# After running this script:
#   - Create a macvlan network in WebNetLab UI using the same subnet/gateway
#   - Set parent interface to the detected/specified NIC
#   - Devices will appear on your LAN and be reachable by your NMS
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "This script must be run as root (sudo)."

# ── OS check ─────────────────────────────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]] || error "This script is for Linux only."

# ── Arguments ─────────────────────────────────────────────────────────────────
PARENT_IFACE="${1:-}"
SUBNET="${2:-192.168.100.0/24}"
GATEWAY="${3:-192.168.100.1}"

# Auto-detect default NIC if not specified
if [[ -z "$PARENT_IFACE" ]]; then
    PARENT_IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="dev") print $(i+1)}' | head -1)
    [[ -n "$PARENT_IFACE" ]] || error "Could not auto-detect default NIC. Pass it as first argument."
    info "Auto-detected default NIC: $PARENT_IFACE"
fi

# Validate NIC exists
ip link show "$PARENT_IFACE" &>/dev/null || error "Interface '$PARENT_IFACE' not found. Available: $(ls /sys/class/net/ | tr '\n' ' ')"

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         WebNetLab macvlan Setup                      ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
echo
info "Parent interface : $PARENT_IFACE"
info "Subnet           : $SUBNET"
info "Gateway          : $GATEWAY"
echo

# ── Step 1: Enable promiscuous mode ───────────────────────────────────────────
info "Step 1/3 — Enabling promiscuous mode on $PARENT_IFACE..."
ip link set "$PARENT_IFACE" promisc on
success "Promiscuous mode enabled on $PARENT_IFACE"

# Check if already persistent
if command -v systemctl &>/dev/null && systemctl is-active --quiet systemd-networkd 2>/dev/null; then
    NETWORKD_CONF="/etc/systemd/network/10-${PARENT_IFACE}-promisc.conf"
    if [[ ! -f "$NETWORKD_CONF" ]]; then
        cat > "$NETWORKD_CONF" << EOF
[Match]
Name=${PARENT_IFACE}

[Link]
Promiscuous=yes
EOF
        success "Persisted via systemd-networkd: $NETWORKD_CONF"
    else
        info "systemd-networkd config already exists, skipping."
    fi
elif [[ -f /etc/rc.local ]]; then
    if ! grep -q "promisc on" /etc/rc.local; then
        sed -i "s|^exit 0|ip link set $PARENT_IFACE promisc on\nexit 0|" /etc/rc.local
        success "Persisted via /etc/rc.local"
    fi
else
    warn "Could not persist promiscuous mode automatically."
    warn "Add 'ip link set $PARENT_IFACE promisc on' to your startup scripts."
fi

# ── Step 2: Host-to-container macvlan shim ────────────────────────────────────
info "Step 2/3 — Creating macvlan shim so the host can reach containers..."
SHIM_IFACE="macvlan-shim"
SHIM_IP=$(echo "$SUBNET" | awk -F'[./]' '{printf "%d.%d.%d.200", $1,$2,$3}')  # e.g. 192.168.100.200

if ip link show "$SHIM_IFACE" &>/dev/null; then
    info "Shim interface $SHIM_IFACE already exists, recreating..."
    ip link del "$SHIM_IFACE" 2>/dev/null || true
fi

ip link add "$SHIM_IFACE" link "$PARENT_IFACE" type macvlan mode bridge
ip addr add "${SHIM_IP}/32" dev "$SHIM_IFACE"
ip link set "$SHIM_IFACE" up
ip route add "$SUBNET" dev "$SHIM_IFACE"
success "Shim interface $SHIM_IFACE created with IP $SHIM_IP"
info "  The host can now reach containers on $SUBNET via $SHIM_IFACE"

# ── Step 3: Validate Docker macvlan capability ────────────────────────────────
info "Step 3/3 — Validating Docker macvlan kernel support..."
if modprobe macvlan 2>/dev/null; then
    success "macvlan kernel module loaded"
else
    warn "Could not load macvlan module via modprobe (may already be built-in)"
fi

# Quick smoke test: create and remove a test macvlan network
if command -v docker &>/dev/null; then
    TEST_NET="wnetlab-macvlan-test-$$"
    if docker network create \
        --driver macvlan \
        --subnet "$SUBNET" \
        --gateway "$GATEWAY" \
        -o parent="$PARENT_IFACE" \
        "$TEST_NET" &>/dev/null; then
        docker network rm "$TEST_NET" &>/dev/null
        success "Docker macvlan network creation test passed"
    else
        warn "Docker macvlan smoke test failed — check kernel and Docker version"
    fi
else
    warn "Docker not found in PATH, skipping smoke test"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  macvlan setup complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo
echo "Next steps:"
echo "  1. Open WebNetLab UI → Networks → New Network"
echo "  2. Type: macvlan"
echo "  3. Parent interface: $PARENT_IFACE"
echo "  4. Subnet: $SUBNET   Gateway: $GATEWAY"
echo "  5. Create devices — they will appear on your LAN"
echo
echo "Your NMS can now reach simulated devices by IP."
echo "Host can reach containers via shim IP: $SHIM_IP"
echo
warn "NOTE: The shim interface and promisc mode are not persistent across reboots"
warn "unless you configured systemd-networkd or rc.local above."
warn "Re-run this script after reboot, or configure systemd-networkd manually."
