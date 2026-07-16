#!/usr/bin/env python3
"""
sacramento_import.py — WebNetLab seed script

Reads topology_raw.json (at the repo root) and creates:
  - 1 Docker bridge network  (sac-lab / 192.168.200.0/24)
  - 5 simulated devices matching the real Sacramento Cisco topology
  - ifDescr OID values for every interface on each device
  - Topology links matching CDP-verified neighbours

Usage (from repo root):
    python webnetlab/seeds/sacramento_import.py [--base-url http://localhost:8000]

Requirements: requests  (pip install requests)
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

# ---------------------------------------------------------------------------
# Parsed topology data extracted directly from topology_raw.json
# ---------------------------------------------------------------------------

DEVICES = [
    {
        "name": "Sac-WAN-1",
        "type": "router",
        "ip_address": "192.168.200.10",
        "snmp_community": "public",
        "real_ip": "192.168.1.18",
        "interfaces": [
            "FastEthernet0/0",
            "Ethernet1/0",
            "Ethernet1/1",
            "Ethernet1/2",
            "Ethernet1/3",
            "Loopback0",
        ],
        "sys_descr": "Cisco IOS Software, 7200 Software (C7200-ADVENTERPRISEK9-M), Version 15.2(4)S7",
        "sys_name": "Sac-WAN-1",
    },
    {
        "name": "Sac-Core1",
        "type": "switch",
        "ip_address": "192.168.200.11",
        "snmp_community": "public",
        "real_ip": "192.168.170.2",
        "interfaces": [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
            "GigabitEthernet1/0",
            "GigabitEthernet1/1",
            "GigabitEthernet1/2",
            "GigabitEthernet1/3",
            "Port-channel1",
            "Vlan500",
            "Vlan600",
            "Vlan700",
        ],
        "sys_descr": "Cisco IOS Software, vios_l2 Software (vios_l2-ADVENTERPRISEK9-M), Experimental Version 15.2(20170321:233949)",
        "sys_name": "Sac-Core1",
    },
    {
        "name": "Sac-Core2",
        "type": "switch",
        "ip_address": "192.168.200.12",
        "snmp_community": "public",
        "real_ip": "192.168.170.3",
        "interfaces": [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
            "GigabitEthernet1/0",
            "GigabitEthernet1/1",
            "GigabitEthernet1/2",
            "GigabitEthernet1/3",
            "Port-channel1",
            "Vlan500",
            "Vlan600",
            "Vlan700",
        ],
        "sys_descr": "Cisco IOS Software, vios_l2 Software (vios_l2-ADVENTERPRISEK9-M), Experimental Version 15.2(20170321:233949)",
        "sys_name": "Sac-Core2",
    },
    {
        "name": "Sac-Dist1",
        "type": "switch",
        "ip_address": "192.168.200.13",
        "snmp_community": "public",
        "real_ip": "192.168.170.4",
        "interfaces": [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
            "GigabitEthernet1/0",
            "GigabitEthernet1/1",
            "GigabitEthernet1/2",
            "GigabitEthernet1/3",
            "Vlan500",
        ],
        "sys_descr": "Cisco IOS Software, vios_l2 Software (vios_l2-ADVENTERPRISEK9-M), Experimental Version 15.2(20170321:233949)",
        "sys_name": "Sac-Dist1",
    },
    {
        "name": "Sac-Dist2",
        "type": "switch",
        "ip_address": "192.168.200.14",
        "snmp_community": "public",
        "real_ip": "192.168.170.5",
        "interfaces": [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
            "GigabitEthernet1/0",
            "GigabitEthernet1/1",
            "GigabitEthernet1/2",
            "GigabitEthernet1/3",
            "Vlan500",
        ],
        "sys_descr": "Cisco IOS Software, vios_l2 Software (vios_l2-ADVENTERPRISEK9-M), Experimental Version 15.2(20170321:233949)",
        "sys_name": "Sac-Dist2",
    },
]

# CDP-verified links: (src_name, src_interface, dst_name, dst_interface)
CDP_LINKS = [
    ("Sac-WAN-1",  "Ethernet1/0",        "Sac-Core1",  "GigabitEthernet0/3"),
    ("Sac-Core1",  "GigabitEthernet0/1", "Sac-Dist1",  "GigabitEthernet0/0"),
    ("Sac-Core1",  "GigabitEthernet0/2", "Sac-Dist2",  "GigabitEthernet0/1"),
    ("Sac-Core2",  "GigabitEthernet0/2", "Sac-Dist1",  "GigabitEthernet0/1"),
    ("Sac-Core2",  "GigabitEthernet0/1", "Sac-Dist2",  "GigabitEthernet0/0"),
    ("Sac-Core1",  "GigabitEthernet1/0", "Sac-Core2",  "GigabitEthernet1/0"),
]

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def build_oid_bulk(device: dict) -> list[dict]:
    """Build OID update list for a device from its known interface data."""
    updates = []

    def s(oid, val, typ="string"):
        return {"oid": oid, "value_mode": "static", "static_value": str(val), "value_type": typ}

    def r(oid, lo, hi, typ="counter"):
        return {"oid": oid, "value_mode": "random", "random_config": {"min": lo, "max": hi, "type": typ}}

    # sysDescr  1.3.6.1.2.1.1.1.0
    updates.append(s("1.3.6.1.2.1.1.1.0", device["sys_descr"]))
    # sysName   1.3.6.1.2.1.1.5.0
    updates.append(s("1.3.6.1.2.1.1.5.0", device["sys_name"]))
    # sysUpTime 1.3.6.1.2.1.1.3.0  — timeticks
    updates.append(r("1.3.6.1.2.1.1.3.0", 100000, 999999999, "timeticks"))
    # ifNumber  1.3.6.1.2.1.2.1.0
    updates.append(s("1.3.6.1.2.1.2.1.0", len(device["interfaces"]), "integer"))

    # ifTable entries per interface (1-based index)
    for idx, iface in enumerate(device["interfaces"], start=1):
        base = "1.3.6.1.2.1.2.2.1"
        # ifIndex
        updates.append(s(f"{base}.1.{idx}", idx, "integer"))
        # ifDescr
        updates.append(s(f"{base}.2.{idx}", iface))
        # ifType  6=ethernetCsmacd 24=softwareLoopback 53=propVirtual 131=tunnel 161=ieee8023adLag
        if "Loopback" in iface:
            iftype = 24
        elif "Tunnel" in iface:
            iftype = 131
        elif "Vlan" in iface:
            iftype = 53
        elif "Port-channel" in iface:
            iftype = 161
        else:
            iftype = 6
        updates.append(s(f"{base}.3.{idx}", iftype, "integer"))
        # ifMtu
        updates.append(s(f"{base}.4.{idx}", 1500, "integer"))
        # ifSpeed (Gauge32)
        if "GigabitEthernet" in iface or "Vlan" in iface or "Port-channel" in iface:
            speed = 1000000000
        elif "FastEthernet" in iface:
            speed = 100000000
        else:
            speed = 10000000
        updates.append(s(f"{base}.5.{idx}", speed, "gauge"))
        # ifAdminStatus / ifOperStatus  1=up (INTEGER)
        updates.append(s(f"{base}.7.{idx}", 1, "integer"))
        updates.append(s(f"{base}.8.{idx}", 1, "integer"))
        # ifInOctets / ifOutOctets (Counter32)
        updates.append(r(f"{base}.10.{idx}", 0, 4294967295, "counter"))
        updates.append(r(f"{base}.16.{idx}", 0, 4294967295, "counter"))

    return updates


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

def run(base_url: str) -> None:
    base = base_url.rstrip("/")
    print(f"Connecting to WebNetLab at {base} ...")

    # 1 — Health check
    r = requests.get(f"{base}/health", timeout=5)
    r.raise_for_status()
    print(f"  ✓ Backend healthy: {r.json()}")

    # 2 — Create network
    print("\n[1/4] Creating Docker network sac-lab (192.168.200.0/24) ...")
    r = requests.post(f"{base}/api/networks", json={
        "name": "sac-lab",
        "type": "bridge",
        "subnet": "192.168.200.0/24",
        "gateway": "192.168.200.1",
    }, timeout=15)
    if r.status_code == 409:
        print("  ↳ Network already exists, fetching ID ...")
        networks = requests.get(f"{base}/api/networks", timeout=5).json()
        net = next(n for n in networks if n["name"] == "sac-lab")
        net_id = net["id"]
    else:
        r.raise_for_status()
        net_id = r.json()["id"]
    print(f"  ✓ Network ID={net_id}")

    # 3 — Create devices
    print("\n[2/4] Creating 5 simulated devices ...")
    name_to_id: dict[str, int] = {}
    for dev in DEVICES:
        payload = {
            "name": dev["name"],
            "type": dev["type"],
            "ip_address": dev["ip_address"],
            "network_id": net_id,
            "snmp_community": dev["snmp_community"],
        }
        r = requests.post(f"{base}/api/devices", json=payload, timeout=30)
        r.raise_for_status()
        dev_id = r.json()["id"]
        name_to_id[dev["name"]] = dev_id
        print(f"  ✓ {dev['name']} → device_id={dev_id}  ip={dev['ip_address']}")

    # 4 — Seed OID values
    print("\n[3/4] Seeding OID values (ifDescr, sysDescr, counters) ...")
    for dev in DEVICES:
        dev_id = name_to_id[dev["name"]]
        updates = build_oid_bulk(dev)
        r = requests.post(
            f"{base}/api/devices/{dev_id}/oids/bulk",
            json={"updates": updates},
            timeout=30,
        )
        r.raise_for_status()
        count = r.json().get("updated", len(updates))
        print(f"  ✓ {dev['name']} — {count} OIDs seeded")

    # 5 — Create topology links
    print("\n[4/4] Creating topology links (CDP-verified) ...")
    for src_name, src_iface, dst_name, dst_iface in CDP_LINKS:
        src_id = name_to_id[src_name]
        dst_id = name_to_id[dst_name]
        r = requests.post(f"{base}/api/topology/links", json={
            "src_device_id": src_id,
            "src_interface": src_iface,
            "dst_device_id": dst_id,
            "dst_interface": dst_iface,
        }, timeout=30)
        r.raise_for_status()
        link = r.json()
        print(f"  ✓ {src_name}:{src_iface} ↔ {dst_name}:{dst_iface}  "
              f"[docker_net={link.get('docker_network_id','?')[:12]}...]")

    # 6 — Summary
    print("\n" + "═" * 60)
    print("Sacramento topology imported successfully!")
    print(f"  Devices : {len(DEVICES)}")
    print(f"  Links   : {len(CDP_LINKS)}")
    print(f"\nOpen http://localhost:5173/topology to see the canvas.")
    print(f"\nTest SNMP (requires net-snmp or Docker):")
    for dev in DEVICES:
        print(f"  snmpget -v2c -c public {dev['ip_address']} 1.3.6.1.2.1.1.5.0  # {dev['name']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Sacramento topology into WebNetLab")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="WebNetLab backend URL (default: http://localhost:8000)")
    args = parser.parse_args()
    run(args.base_url)
