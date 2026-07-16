# WebNetLab — Seed Scripts

## sacramento_import.py

Imports the **Sacramento network topology** (5 real Cisco devices) into a running WebNetLab instance.

### What it creates

| Device | Simulated IP | Type | Real IP |
|---|---|---|---|
| Sac-WAN-1 | 192.168.200.10 | router | 192.168.1.18 |
| Sac-Core1 | 192.168.200.11 | switch | 192.168.170.2 |
| Sac-Core2 | 192.168.200.12 | switch | 192.168.170.3 |
| Sac-Dist1 | 192.168.200.13 | switch | 192.168.170.4 |
| Sac-Dist2 | 192.168.200.14 | switch | 192.168.170.5 |

### Topology (CDP-verified)

```
Sac-WAN-1 (Et1/0) ──────────── (Gi0/3) Sac-Core1
                                          │
                              (Gi0/1) ───┤──── (Gi0/0) Sac-Dist1
                              (Gi0/2) ───┘──── (Gi0/1) Sac-Dist2

Sac-Core2 (Gi0/2) ──────────── (Gi0/1) Sac-Dist1
          (Gi0/1) ──────────── (Gi0/0) Sac-Dist2
          (Gi1/0) ──────────── (Gi1/0) Sac-Core1  [inter-core link]
```

### OIDs seeded per device

- `sysDescr` (1.3.6.1.2.1.1.1.0) — real Cisco IOS version string
- `sysName` (1.3.6.1.2.1.1.5.0) — hostname
- `sysUpTime` (1.3.6.1.2.1.1.3.0) — random counter
- `ifNumber` (1.3.6.1.2.1.2.1.0) — interface count
- `ifTable` (1.3.6.1.2.1.2.2.1.*) — full ifDescr, ifType, ifMtu, ifSpeed, ifAdminStatus, ifOperStatus, ifInOctets, ifOutOctets per interface

### Usage

Make sure WebNetLab containers are running:
```bash
cd webnetlab
docker compose up -d
```

Then run the import:
```bash
pip install requests
python webnetlab/seeds/sacramento_import.py
```

Or point at a different host:
```bash
python webnetlab/seeds/sacramento_import.py --base-url http://192.168.1.100:8000
```

### Verify with snmpget

After import, test any device:
```bash
# sysName
snmpget -v2c -c public 192.168.200.10 1.3.6.1.2.1.1.5.0
# Expected: STRING: "Sac-WAN-1"

# ifDescr on interface 1
snmpget -v2c -c public 192.168.200.11 1.3.6.1.2.1.2.2.1.2.1
# Expected: STRING: "GigabitEthernet0/0"
```

If `snmpget` is not installed, use Docker:
```bash
docker run --rm --network sac-lab elcolio/net-snmp \
  snmpget -v2c -c public 192.168.200.10 1.3.6.1.2.1.1.5.0
```

### Re-running

The script is idempotent-safe for the network (409 handled). Re-running will fail on devices if IPs already exist — delete existing devices first via the UI or `DELETE /api/devices/{id}`.
