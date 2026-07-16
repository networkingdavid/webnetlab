# Linux LAN Mode — macvlan / ipvlan

On Linux, WebNetLab can place simulated devices directly on your **physical LAN** so any NMS, Wireshark capture, or real device on that segment sees them as genuine SNMP-speaking hardware.

This document explains both modes, when to use each, and how to set them up.

---

## How it works

Both modes attach Docker containers to a real physical NIC on the host:

```
Physical LAN  ←→  eth0 (host NIC)  ←→  macvlan/ipvlan interface  ←→  container
```

The container has:
- Its own **IP address** from your LAN subnet (or a dedicated subnet on the LAN)
- Port 161/UDP open and answered by the WebNetLab SNMP agent
- A static MAC address (macvlan) or shared host MAC (ipvlan)

Your NMS queries `<container-ip>:161` directly — no port mapping, no tunneling.

---

## macvlan vs ipvlan

| Feature | macvlan | ipvlan (L2) |
|---|---|---|
| Container MAC | **Unique** per container | Shared with host |
| NMS sees distinct device | ✅ Yes | ✅ Yes (by IP) |
| Promiscuous mode required | ✅ Yes | ❌ No |
| Works on AWS / GCP / VMware | ❌ Usually blocked (MAC spoofing) | ✅ Usually works |
| Works on bare metal / KVM | ✅ Yes | ✅ Yes |

**Recommendation:** Use **macvlan** on bare metal or KVM. Use **ipvlan** on cloud VMs.

---

## Prerequisites

- Linux host (Ubuntu 20.04+, Debian 11+, RHEL 8+, etc.)
- Docker Engine 20.10+
- A physical NIC with LAN access (e.g. `eth0`, `ens3`, `enp3s0`)
- `sudo` access to enable promiscuous mode

---

## Quick setup

```bash
# 1. Run the setup script (detects your NIC automatically)
sudo bash infra/linux-macvlan-setup.sh

# Or specify NIC, subnet, and gateway explicitly:
sudo bash infra/linux-macvlan-setup.sh eth0 192.168.100.0/24 192.168.100.1
```

The script will:
1. Enable **promiscuous mode** on your NIC
2. Create a **macvlan shim** interface so the Linux host itself can reach containers
3. Run a Docker smoke test to confirm macvlan works

---

## Step-by-step (manual)

### 1. Enable promiscuous mode

```bash
sudo ip link set eth0 promisc on

# Verify
ip link show eth0 | grep PROMISC
```

### 2. Create the macvlan shim (host → container routing)

Linux cannot communicate with its own macvlan children by default.
Create a shim interface so the host itself can reach them:

```bash
sudo ip link add macvlan-shim link eth0 type macvlan mode bridge
sudo ip addr add 192.168.100.200/32 dev macvlan-shim
sudo ip link set macvlan-shim up
sudo ip route add 192.168.100.0/24 dev macvlan-shim
```

### 3. Create a macvlan network in WebNetLab

1. Open **Networks** → **New Network**
2. Type: **Macvlan — LAN (Linux)**
3. Parent interface: `eth0`
4. Subnet: `192.168.100.0/24`
5. Gateway: `192.168.100.1`

> ⚠️ The subnet you enter must not overlap with your existing LAN subnet unless you plan to use IPs from the same range. Using a dedicated subnet like `192.168.100.0/24` avoids IP conflicts.

### 4. Create devices

Create devices on that network with IPs in your chosen subnet (e.g. `192.168.100.10`).
From any machine on the LAN:

```bash
snmpget -v2c -c public 192.168.100.10 1.3.6.1.2.1.1.5.0
```

---

## Persistence across reboots

Promiscuous mode and the shim interface are **not persistent** by default.

### Option A — systemd-networkd

```ini
# /etc/systemd/network/10-eth0-promisc.conf
[Match]
Name=eth0

[Link]
Promiscuous=yes
```

```bash
sudo systemctl restart systemd-networkd
```

### Option B — Netplan (Ubuntu 20.04+)

```yaml
# /etc/netplan/01-eth0.yaml
network:
  ethernets:
    eth0:
      dhcp4: true
      match:
        name: eth0
      set-name: eth0
```
Add `optional: true` if needed, then `sudo netplan apply`.

### Option C — rc.local

```bash
# Add to /etc/rc.local before 'exit 0':
ip link set eth0 promisc on
ip link add macvlan-shim link eth0 type macvlan mode bridge
ip addr add 192.168.100.200/32 dev macvlan-shim
ip link set macvlan-shim up
ip route add 192.168.100.0/24 dev macvlan-shim
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker network create` fails with "operation not supported" | macvlan kernel module not loaded | `sudo modprobe macvlan` |
| NMS can't reach containers | Promiscuous mode not enabled | `sudo ip link set eth0 promisc on` |
| Host (Linux) can't reach containers | Shim not created | Re-run setup script |
| macvlan fails on VM | Hypervisor blocks MAC spoofing | Switch to ipvlan mode |
| Container starts but no SNMP reply | Agent bound to wrong IP | Restart device in WebNetLab UI |

---

## macOS users

macOS is **not supported** for LAN modes. Docker Desktop runs containers inside a Linux VM and cannot bridge to `en0` or any physical Mac NIC.

On macOS, use **Host-accessible Bridge** — Docker Desktop automatically routes the container subnet to your Mac, so your NMS can reach devices by container IP without any port mapping.

See the main [README](../README.md) for macOS quick-start.
