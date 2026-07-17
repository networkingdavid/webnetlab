"""Parse the text output of `snmpwalk -v2c -c public <host>` into OID/value pairs.

Handles two line formats:
  Format 1 (symbolic): IF-MIB::ifDescr.1 = STRING: GigabitEthernet0/0
  Format 2 (raw OID):  .1.3.6.1.2.1.2.2.1.2.1 = STRING: GigabitEthernet0/0

OID resolution strategy
-----------------------
1. Raw dotted-numeric lines (.1.3.6.1...) → used directly.
2. Symbolic lines (MODULE::name.instance):
   a. Looked up in _OID_TABLE — a static map of 250+ common IETF / Cisco MIB
      objects.  This is reliable and zero-latency regardless of which pysnmp
      version (or none) is installed.
   b. If not in the table, attempted via the pysnmp MIB engine (best-effort).
   c. If that also fails, the entry is SKIPPED (not stored as a symbolic key
      which would crash the SNMP agent).

Type mapping
------------
The snmpwalk TYPE tag (STRING, INTEGER, Counter32, Gauge32, Timeticks,
IpAddress, OID, Hex-STRING, …) is captured and normalised to the
WebNetLab value_type vocabulary:
  STRING / Hex-STRING / OID  → "string"
  INTEGER                    → "integer"
  Counter32 / Counter64      → "counter"
  Gauge32 / Gauge64          → "gauge"
  Timeticks                  → "timeticks"  (value stripped to integer)
  IpAddress                  → "ipaddress"
"""

import re
from typing import NamedTuple


class WalkEntry(NamedTuple):
    oid:        str   # dotted numeric, e.g. "1.3.6.1.2.1.2.2.1.2.1"
    value:      str   # cleaned value string (Timeticks → just the integer)
    value_type: str   # "string" | "integer" | "counter" | "gauge" | "timeticks" | "ipaddress"


def is_numeric_oid(oid: str) -> bool:
    """Return True only if every dot-separated segment is a non-negative integer."""
    if not oid:
        return False
    return all(seg.isdigit() for seg in oid.strip(".").split("."))


# ---------------------------------------------------------------------------
# Static OID table — MODULE::objectName → dotted-numeric prefix
#
# Each value is the base OID *without* instance suffix.
# The instance suffix from the walk line (e.g. ".1", ".0") is appended separately.
# ---------------------------------------------------------------------------

_OID_TABLE: dict[str, str] = {
    # ── SNMPv2-MIB (system group) ──────────────────────────────────────────
    "SNMPv2-MIB::sysDescr":             "1.3.6.1.2.1.1.1",
    "SNMPv2-MIB::sysObjectID":          "1.3.6.1.2.1.1.2",
    "SNMPv2-MIB::sysUpTime":            "1.3.6.1.2.1.1.3",
    "SNMPv2-MIB::sysContact":           "1.3.6.1.2.1.1.4",
    "SNMPv2-MIB::sysName":              "1.3.6.1.2.1.1.5",
    "SNMPv2-MIB::sysLocation":          "1.3.6.1.2.1.1.6",
    "SNMPv2-MIB::sysServices":          "1.3.6.1.2.1.1.7",
    "SNMPv2-MIB::sysORLastChange":      "1.3.6.1.2.1.1.8",
    # ── DISMAN-EVENT-MIB ──────────────────────────────────────────────────
    "DISMAN-EVENT-MIB::sysUpTimeInstance": "1.3.6.1.2.1.1.3.0",  # special: no extra inst
    # ── IF-MIB ────────────────────────────────────────────────────────────
    "IF-MIB::ifNumber":                 "1.3.6.1.2.1.2.1",
    "IF-MIB::ifIndex":                  "1.3.6.1.2.1.2.2.1.1",
    "IF-MIB::ifDescr":                  "1.3.6.1.2.1.2.2.1.2",
    "IF-MIB::ifType":                   "1.3.6.1.2.1.2.2.1.3",
    "IF-MIB::ifMtu":                    "1.3.6.1.2.1.2.2.1.4",
    "IF-MIB::ifSpeed":                  "1.3.6.1.2.1.2.2.1.5",
    "IF-MIB::ifPhysAddress":            "1.3.6.1.2.1.2.2.1.6",
    "IF-MIB::ifAdminStatus":            "1.3.6.1.2.1.2.2.1.7",
    "IF-MIB::ifOperStatus":             "1.3.6.1.2.1.2.2.1.8",
    "IF-MIB::ifLastChange":             "1.3.6.1.2.1.2.2.1.9",
    "IF-MIB::ifInOctets":               "1.3.6.1.2.1.2.2.1.10",
    "IF-MIB::ifInUcastPkts":            "1.3.6.1.2.1.2.2.1.11",
    "IF-MIB::ifInNUcastPkts":           "1.3.6.1.2.1.2.2.1.12",
    "IF-MIB::ifInDiscards":             "1.3.6.1.2.1.2.2.1.13",
    "IF-MIB::ifInErrors":               "1.3.6.1.2.1.2.2.1.14",
    "IF-MIB::ifInUnknownProtos":        "1.3.6.1.2.1.2.2.1.15",
    "IF-MIB::ifOutOctets":              "1.3.6.1.2.1.2.2.1.16",
    "IF-MIB::ifOutUcastPkts":           "1.3.6.1.2.1.2.2.1.17",
    "IF-MIB::ifOutNUcastPkts":          "1.3.6.1.2.1.2.2.1.18",
    "IF-MIB::ifOutDiscards":            "1.3.6.1.2.1.2.2.1.19",
    "IF-MIB::ifOutErrors":              "1.3.6.1.2.1.2.2.1.20",
    "IF-MIB::ifOutQLen":                "1.3.6.1.2.1.2.2.1.21",
    "IF-MIB::ifSpecific":               "1.3.6.1.2.1.2.2.1.22",
    # IF-MIB::ifXTable (ifMIB extensions — RFC 2233)
    "IF-MIB::ifName":                   "1.3.6.1.2.1.31.1.1.1.1",
    "IF-MIB::ifInMulticastPkts":        "1.3.6.1.2.1.31.1.1.1.2",
    "IF-MIB::ifInBroadcastPkts":        "1.3.6.1.2.1.31.1.1.1.3",
    "IF-MIB::ifOutMulticastPkts":       "1.3.6.1.2.1.31.1.1.1.4",
    "IF-MIB::ifOutBroadcastPkts":       "1.3.6.1.2.1.31.1.1.1.5",
    "IF-MIB::ifHCInOctets":             "1.3.6.1.2.1.31.1.1.1.6",
    "IF-MIB::ifHCInUcastPkts":          "1.3.6.1.2.1.31.1.1.1.7",
    "IF-MIB::ifHCInMulticastPkts":      "1.3.6.1.2.1.31.1.1.1.8",
    "IF-MIB::ifHCInBroadcastPkts":      "1.3.6.1.2.1.31.1.1.1.9",
    "IF-MIB::ifHCOutOctets":            "1.3.6.1.2.1.31.1.1.1.10",
    "IF-MIB::ifHCOutUcastPkts":         "1.3.6.1.2.1.31.1.1.1.11",
    "IF-MIB::ifHCOutMulticastPkts":     "1.3.6.1.2.1.31.1.1.1.12",
    "IF-MIB::ifHCOutBroadcastPkts":     "1.3.6.1.2.1.31.1.1.1.13",
    "IF-MIB::ifLinkUpDownTrapEnable":   "1.3.6.1.2.1.31.1.1.1.14",
    "IF-MIB::ifHighSpeed":              "1.3.6.1.2.1.31.1.1.1.15",
    "IF-MIB::ifPromiscuousMode":        "1.3.6.1.2.1.31.1.1.1.16",
    "IF-MIB::ifConnectorPresent":       "1.3.6.1.2.1.31.1.1.1.17",
    "IF-MIB::ifAlias":                  "1.3.6.1.2.1.31.1.1.1.18",
    "IF-MIB::ifCounterDiscontinuityTime": "1.3.6.1.2.1.31.1.1.1.19",
    # ── IP-MIB (RFC 4293) ─────────────────────────────────────────────────
    "IP-MIB::ipForwarding":             "1.3.6.1.2.1.4.1",
    "IP-MIB::ipDefaultTTL":             "1.3.6.1.2.1.4.2",
    "IP-MIB::ipInReceives":             "1.3.6.1.2.1.4.3",
    "IP-MIB::ipInHdrErrors":            "1.3.6.1.2.1.4.4",
    "IP-MIB::ipInAddrErrors":           "1.3.6.1.2.1.4.5",
    "IP-MIB::ipForwDatagrams":          "1.3.6.1.2.1.4.6",
    "IP-MIB::ipInUnknownProtos":        "1.3.6.1.2.1.4.7",
    "IP-MIB::ipInDiscards":             "1.3.6.1.2.1.4.8",
    "IP-MIB::ipInDelivers":             "1.3.6.1.2.1.4.9",
    "IP-MIB::ipOutRequests":            "1.3.6.1.2.1.4.10",
    "IP-MIB::ipOutDiscards":            "1.3.6.1.2.1.4.11",
    "IP-MIB::ipOutNoRoutes":            "1.3.6.1.2.1.4.12",
    "IP-MIB::ipReasmTimeout":           "1.3.6.1.2.1.4.13",
    "IP-MIB::ipReasmReqds":             "1.3.6.1.2.1.4.14",
    "IP-MIB::ipReasmOKs":              "1.3.6.1.2.1.4.15",
    "IP-MIB::ipReasmFails":             "1.3.6.1.2.1.4.16",
    "IP-MIB::ipFragOKs":               "1.3.6.1.2.1.4.17",
    "IP-MIB::ipFragFails":              "1.3.6.1.2.1.4.18",
    "IP-MIB::ipFragCreates":            "1.3.6.1.2.1.4.19",
    "IP-MIB::ipAdEntAddr":              "1.3.6.1.2.1.4.20.1.1",
    "IP-MIB::ipAdEntIfIndex":           "1.3.6.1.2.1.4.20.1.2",
    "IP-MIB::ipAdEntNetMask":           "1.3.6.1.2.1.4.20.1.3",
    "IP-MIB::ipAdEntBcastAddr":         "1.3.6.1.2.1.4.20.1.4",
    "IP-MIB::ipAdEntReasmMaxSize":      "1.3.6.1.2.1.4.20.1.5",
    "IP-MIB::ipRouteDest":              "1.3.6.1.2.1.4.21.1.1",
    "IP-MIB::ipRouteIfIndex":           "1.3.6.1.2.1.4.21.1.2",
    "IP-MIB::ipRouteMetric1":           "1.3.6.1.2.1.4.21.1.3",
    "IP-MIB::ipRouteNextHop":           "1.3.6.1.2.1.4.21.1.7",
    "IP-MIB::ipRouteType":              "1.3.6.1.2.1.4.21.1.8",
    "IP-MIB::ipRouteProto":             "1.3.6.1.2.1.4.21.1.9",
    # ── TCP-MIB ───────────────────────────────────────────────────────────
    "TCP-MIB::tcpActiveOpens":          "1.3.6.1.2.1.6.5",
    "TCP-MIB::tcpPassiveOpens":         "1.3.6.1.2.1.6.6",
    "TCP-MIB::tcpAttemptFails":         "1.3.6.1.2.1.6.7",
    "TCP-MIB::tcpEstabResets":          "1.3.6.1.2.1.6.8",
    "TCP-MIB::tcpCurrEstab":            "1.3.6.1.2.1.6.9",
    "TCP-MIB::tcpInSegs":               "1.3.6.1.2.1.6.10",
    "TCP-MIB::tcpOutSegs":              "1.3.6.1.2.1.6.11",
    "TCP-MIB::tcpRetransSegs":          "1.3.6.1.2.1.6.12",
    "TCP-MIB::tcpInErrs":               "1.3.6.1.2.1.6.14",
    "TCP-MIB::tcpOutRsts":              "1.3.6.1.2.1.6.15",
    # ── UDP-MIB ───────────────────────────────────────────────────────────
    "UDP-MIB::udpInDatagrams":          "1.3.6.1.2.1.7.1",
    "UDP-MIB::udpNoPorts":              "1.3.6.1.2.1.7.2",
    "UDP-MIB::udpInErrors":             "1.3.6.1.2.1.7.3",
    "UDP-MIB::udpOutDatagrams":         "1.3.6.1.2.1.7.4",
    # ── SNMP-MIB (RFC 1907) ───────────────────────────────────────────────
    "SNMPv2-MIB::snmpInPkts":           "1.3.6.1.2.1.11.1",
    "SNMPv2-MIB::snmpOutPkts":          "1.3.6.1.2.1.11.2",
    "SNMPv2-MIB::snmpInBadVersions":    "1.3.6.1.2.1.11.3",
    "SNMPv2-MIB::snmpInBadCommunityNames": "1.3.6.1.2.1.11.4",
    "SNMPv2-MIB::snmpInBadCommunityUses": "1.3.6.1.2.1.11.5",
    "SNMPv2-MIB::snmpInASNParseErrs":   "1.3.6.1.2.1.11.6",
    "SNMPv2-MIB::snmpInTotalReqVars":   "1.3.6.1.2.1.11.9",
    "SNMPv2-MIB::snmpInGetRequests":    "1.3.6.1.2.1.11.15",
    "SNMPv2-MIB::snmpInGetNexts":       "1.3.6.1.2.1.11.16",
    "SNMPv2-MIB::snmpInSetRequests":    "1.3.6.1.2.1.11.17",
    "SNMPv2-MIB::snmpInGetResponses":   "1.3.6.1.2.1.11.18",
    "SNMPv2-MIB::snmpInTraps":          "1.3.6.1.2.1.11.19",
    "SNMPv2-MIB::snmpOutGetRequests":   "1.3.6.1.2.1.11.20",
    "SNMPv2-MIB::snmpOutGetNexts":      "1.3.6.1.2.1.11.21",
    "SNMPv2-MIB::snmpOutSetRequests":   "1.3.6.1.2.1.11.22",
    "SNMPv2-MIB::snmpOutGetResponses":  "1.3.6.1.2.1.11.23",
    "SNMPv2-MIB::snmpOutTraps":         "1.3.6.1.2.1.11.24",
    "SNMPv2-MIB::snmpEnableAuthenTraps": "1.3.6.1.2.1.11.30",
    "SNMPv2-MIB::snmpSilentDrops":      "1.3.6.1.2.1.11.31",
    "SNMPv2-MIB::snmpProxyDrops":       "1.3.6.1.2.1.11.32",
    # ── HOST-RESOURCES-MIB (RFC 2790) ────────────────────────────────────
    "HOST-RESOURCES-MIB::hrSystemUptime":        "1.3.6.1.2.1.25.1.1",
    "HOST-RESOURCES-MIB::hrSystemDate":           "1.3.6.1.2.1.25.1.2",
    "HOST-RESOURCES-MIB::hrMemorySize":           "1.3.6.1.2.1.25.2.2",
    "HOST-RESOURCES-MIB::hrStorageIndex":         "1.3.6.1.2.1.25.2.3.1.1",
    "HOST-RESOURCES-MIB::hrStorageType":          "1.3.6.1.2.1.25.2.3.1.2",
    "HOST-RESOURCES-MIB::hrStorageDescr":         "1.3.6.1.2.1.25.2.3.1.3",
    "HOST-RESOURCES-MIB::hrStorageAllocationUnits": "1.3.6.1.2.1.25.2.3.1.4",
    "HOST-RESOURCES-MIB::hrStorageSize":          "1.3.6.1.2.1.25.2.3.1.5",
    "HOST-RESOURCES-MIB::hrStorageUsed":          "1.3.6.1.2.1.25.2.3.1.6",
    "HOST-RESOURCES-MIB::hrProcessorFrwID":       "1.3.6.1.2.1.25.3.3.1.1",
    "HOST-RESOURCES-MIB::hrProcessorLoad":        "1.3.6.1.2.1.25.3.3.1.2",
    # ── ENTITY-MIB (RFC 4133) ─────────────────────────────────────────────
    "ENTITY-MIB::entPhysicalDescr":      "1.3.6.1.2.1.47.1.1.1.1.2",
    "ENTITY-MIB::entPhysicalVendorType": "1.3.6.1.2.1.47.1.1.1.1.3",
    "ENTITY-MIB::entPhysicalContainedIn":"1.3.6.1.2.1.47.1.1.1.1.4",
    "ENTITY-MIB::entPhysicalClass":      "1.3.6.1.2.1.47.1.1.1.1.5",
    "ENTITY-MIB::entPhysicalParentRelPos":"1.3.6.1.2.1.47.1.1.1.1.6",
    "ENTITY-MIB::entPhysicalName":       "1.3.6.1.2.1.47.1.1.1.1.7",
    "ENTITY-MIB::entPhysicalHardwareRev":"1.3.6.1.2.1.47.1.1.1.1.8",
    "ENTITY-MIB::entPhysicalFirmwareRev":"1.3.6.1.2.1.47.1.1.1.1.9",
    "ENTITY-MIB::entPhysicalSoftwareRev":"1.3.6.1.2.1.47.1.1.1.1.10",
    "ENTITY-MIB::entPhysicalSerialNum":  "1.3.6.1.2.1.47.1.1.1.1.11",
    "ENTITY-MIB::entPhysicalMfgName":    "1.3.6.1.2.1.47.1.1.1.1.12",
    "ENTITY-MIB::entPhysicalModelName":  "1.3.6.1.2.1.47.1.1.1.1.13",
    "ENTITY-MIB::entPhysicalAlias":      "1.3.6.1.2.1.47.1.1.1.1.14",
    "ENTITY-MIB::entPhysicalAssetID":    "1.3.6.1.2.1.47.1.1.1.1.15",
    "ENTITY-MIB::entPhysicalIsFRU":      "1.3.6.1.2.1.47.1.1.1.1.16",
    # ── BGP4-MIB (RFC 1657) ───────────────────────────────────────────────
    "BGP4-MIB::bgpVersion":              "1.3.6.1.2.1.15.1",
    "BGP4-MIB::bgpLocalAs":              "1.3.6.1.2.1.15.2",
    "BGP4-MIB::bgpPeerState":            "1.3.6.1.2.1.15.3.1.2",
    "BGP4-MIB::bgpPeerAdminStatus":      "1.3.6.1.2.1.15.3.1.3",
    "BGP4-MIB::bgpPeerNegotiatedVersion":"1.3.6.1.2.1.15.3.1.4",
    "BGP4-MIB::bgpPeerLocalAddr":        "1.3.6.1.2.1.15.3.1.5",
    "BGP4-MIB::bgpPeerLocalPort":        "1.3.6.1.2.1.15.3.1.6",
    "BGP4-MIB::bgpPeerRemoteAddr":       "1.3.6.1.2.1.15.3.1.7",
    "BGP4-MIB::bgpPeerRemotePort":       "1.3.6.1.2.1.15.3.1.8",
    "BGP4-MIB::bgpPeerRemoteAs":         "1.3.6.1.2.1.15.3.1.9",
    "BGP4-MIB::bgpPeerInUpdates":        "1.3.6.1.2.1.15.3.1.10",
    "BGP4-MIB::bgpPeerOutUpdates":       "1.3.6.1.2.1.15.3.1.11",
    "BGP4-MIB::bgpPeerInTotalMessages":  "1.3.6.1.2.1.15.3.1.12",
    "BGP4-MIB::bgpPeerOutTotalMessages": "1.3.6.1.2.1.15.3.1.13",
    "BGP4-MIB::bgpPeerLastError":        "1.3.6.1.2.1.15.3.1.14",
    "BGP4-MIB::bgpPeerEstablishedTransitions": "1.3.6.1.2.1.15.3.1.15",
    # ── OSPF-MIB (RFC 1850) ───────────────────────────────────────────────
    "OSPF-MIB::ospfRouterId":            "1.3.6.1.2.1.14.1.1",
    "OSPF-MIB::ospfAdminStat":           "1.3.6.1.2.1.14.1.2",
    "OSPF-MIB::ospfVersionNumber":       "1.3.6.1.2.1.14.1.3",
    "OSPF-MIB::ospfAreaBdrRtrStatus":    "1.3.6.1.2.1.14.1.4",
    "OSPF-MIB::ospfASBdrRtrStatus":      "1.3.6.1.2.1.14.1.5",
    "OSPF-MIB::ospfExternLsaCount":      "1.3.6.1.2.1.14.1.6",
    "OSPF-MIB::ospfOriginateNewLsas":    "1.3.6.1.2.1.14.1.12",
    "OSPF-MIB::ospfRxNewLsas":           "1.3.6.1.2.1.14.1.13",
    "OSPF-MIB::ospfAreaId":              "1.3.6.1.2.1.14.2.1.1",
    "OSPF-MIB::ospfAuthType":            "1.3.6.1.2.1.14.2.1.2",
    "OSPF-MIB::ospfIfIpAddress":         "1.3.6.1.2.1.14.7.1.1",
    "OSPF-MIB::ospfIfState":             "1.3.6.1.2.1.14.7.1.12",
    # ── BRIDGE-MIB (RFC 4188) ─────────────────────────────────────────────
    "BRIDGE-MIB::dot1dBaseBridgeAddress": "1.3.6.1.2.1.17.1.1",
    "BRIDGE-MIB::dot1dBaseNumPorts":      "1.3.6.1.2.1.17.1.2",
    "BRIDGE-MIB::dot1dBaseType":          "1.3.6.1.2.1.17.1.3",
    "BRIDGE-MIB::dot1dBasePort":          "1.3.6.1.2.1.17.1.4.1.1",
    "BRIDGE-MIB::dot1dBasePortIfIndex":   "1.3.6.1.2.1.17.1.4.1.2",
    "BRIDGE-MIB::dot1dStpBridgeMaxAge":   "1.3.6.1.2.1.17.2.8",
    "BRIDGE-MIB::dot1dStpBridgeHelloTime":"1.3.6.1.2.1.17.2.10",
    "BRIDGE-MIB::dot1dStpBridgeForwardDelay": "1.3.6.1.2.1.17.2.12",
    "BRIDGE-MIB::dot1dTpFdbAddress":      "1.3.6.1.2.1.17.4.3.1.1",
    "BRIDGE-MIB::dot1dTpFdbPort":         "1.3.6.1.2.1.17.4.3.1.2",
    "BRIDGE-MIB::dot1dTpFdbStatus":       "1.3.6.1.2.1.17.4.3.1.3",
    # ── Q-BRIDGE-MIB (IEEE 802.1Q VLANs) ────────────────────────────────
    "Q-BRIDGE-MIB::dot1qVlanFdbId":       "1.3.6.1.2.1.17.7.1.4.2.1.3",
    "Q-BRIDGE-MIB::dot1qVlanStaticName":  "1.3.6.1.2.1.17.7.1.4.3.1.1",
    "Q-BRIDGE-MIB::dot1qVlanStaticEgressPorts": "1.3.6.1.2.1.17.7.1.4.3.1.2",
    "Q-BRIDGE-MIB::dot1qVlanStaticUntaggedPorts":"1.3.6.1.2.1.17.7.1.4.3.1.4",
    # ── Cisco IOS / CISCO-MIBs ─────────────────────────────────────────
    # CISCO-PROCESS-MIB (cpmCPU)
    "CISCO-PROCESS-MIB::cpmCPUTotalPhysicalIndex": "1.3.6.1.4.1.9.9.109.1.1.1.1.2",
    "CISCO-PROCESS-MIB::cpmCPUTotal5sec":           "1.3.6.1.4.1.9.9.109.1.1.1.1.3",
    "CISCO-PROCESS-MIB::cpmCPUTotal1min":           "1.3.6.1.4.1.9.9.109.1.1.1.1.4",
    "CISCO-PROCESS-MIB::cpmCPUTotal5min":           "1.3.6.1.4.1.9.9.109.1.1.1.1.5",
    "CISCO-PROCESS-MIB::cpmCPUTotal1minRev":        "1.3.6.1.4.1.9.9.109.1.1.1.1.7",
    "CISCO-PROCESS-MIB::cpmCPUTotal5minRev":        "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
    "CISCO-PROCESS-MIB::cpmCPUMonInterval":         "1.3.6.1.4.1.9.9.109.1.1.1.1.9",
    "CISCO-PROCESS-MIB::cpmCPUTotalMonIntervalValue":"1.3.6.1.4.1.9.9.109.1.1.1.1.10",
    # CISCO-MEMORY-POOL-MIB
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolName":   "1.3.6.1.4.1.9.9.48.1.1.1.2",
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolAlternate": "1.3.6.1.4.1.9.9.48.1.1.1.3",
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolValid":   "1.3.6.1.4.1.9.9.48.1.1.1.4",
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolUsed":   "1.3.6.1.4.1.9.9.48.1.1.1.5",
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolFree":   "1.3.6.1.4.1.9.9.48.1.1.1.6",
    "CISCO-MEMORY-POOL-MIB::ciscoMemoryPoolLargestFree": "1.3.6.1.4.1.9.9.48.1.1.1.7",
    # CISCO-CDP-MIB
    "CISCO-CDP-MIB::cdpInterfaceIfIndex":  "1.3.6.1.4.1.9.9.23.1.1.1.1.1",
    "CISCO-CDP-MIB::cdpInterfaceEnable":   "1.3.6.1.4.1.9.9.23.1.1.1.1.2",
    "CISCO-CDP-MIB::cdpCacheDeviceId":     "1.3.6.1.4.1.9.9.23.1.2.1.1.6",
    "CISCO-CDP-MIB::cdpCacheDevicePort":   "1.3.6.1.4.1.9.9.23.1.2.1.1.7",
    "CISCO-CDP-MIB::cdpCachePlatform":     "1.3.6.1.4.1.9.9.23.1.2.1.1.8",
    "CISCO-CDP-MIB::cdpCacheCapabilities": "1.3.6.1.4.1.9.9.23.1.2.1.1.9",
    "CISCO-CDP-MIB::cdpCacheNativeVLAN":   "1.3.6.1.4.1.9.9.23.1.2.1.1.11",
    # CISCO-IF-EXTENSION-MIB
    "CISCO-IF-EXTENSION-MIB::cieIfLastInTime":  "1.3.6.1.4.1.9.9.276.1.1.2.1.1",
    "CISCO-IF-EXTENSION-MIB::cieIfLastOutTime": "1.3.6.1.4.1.9.9.276.1.1.2.1.2",
    "CISCO-IF-EXTENSION-MIB::cieIfLastOutHangTime": "1.3.6.1.4.1.9.9.276.1.1.2.1.3",
    "CISCO-IF-EXTENSION-MIB::cieIfInputQueueDrops": "1.3.6.1.4.1.9.9.276.1.1.2.1.6",
    "CISCO-IF-EXTENSION-MIB::cieIfOutputQueueDrops":"1.3.6.1.4.1.9.9.276.1.1.2.1.7",
    # CISCO-ENVMON-MIB
    "CISCO-ENVMON-MIB::ciscoEnvMonTemperatureStatusDescr":  "1.3.6.1.4.1.9.9.13.1.3.1.2",
    "CISCO-ENVMON-MIB::ciscoEnvMonTemperatureStatusValue":  "1.3.6.1.4.1.9.9.13.1.3.1.3",
    "CISCO-ENVMON-MIB::ciscoEnvMonTemperatureState":        "1.3.6.1.4.1.9.9.13.1.3.1.6",
    "CISCO-ENVMON-MIB::ciscoEnvMonFanStatusDescr":          "1.3.6.1.4.1.9.9.13.1.4.1.2",
    "CISCO-ENVMON-MIB::ciscoEnvMonFanState":                "1.3.6.1.4.1.9.9.13.1.4.1.3",
    "CISCO-ENVMON-MIB::ciscoEnvMonSupplyStatusDescr":       "1.3.6.1.4.1.9.9.13.1.5.1.2",
    "CISCO-ENVMON-MIB::ciscoEnvMonSupplyState":             "1.3.6.1.4.1.9.9.13.1.5.1.3",
    # CISCO-EIGRP-MIB
    "CISCO-EIGRP-MIB::cEigrpVpnId":      "1.3.6.1.4.1.9.9.449.1.2.1.1.1",
    "CISCO-EIGRP-MIB::cEigrpAsNumber":   "1.3.6.1.4.1.9.9.449.1.2.1.1.2",
    "CISCO-EIGRP-MIB::cEigrpNbrCount":   "1.3.6.1.4.1.9.9.449.1.2.1.1.8",
    # CISCO-HSRP-MIB
    "CISCO-HSRP-MIB::cHsrpGrpActiveRouter":  "1.3.6.1.4.1.9.9.106.1.2.1.1.12",
    "CISCO-HSRP-MIB::cHsrpGrpStandbyRouter": "1.3.6.1.4.1.9.9.106.1.2.1.1.13",
    "CISCO-HSRP-MIB::cHsrpGrpState":         "1.3.6.1.4.1.9.9.106.1.2.1.1.15",
    # CISCO-VLAN-MIB
    "CISCO-VTP-MIB::vtpVlanState":            "1.3.6.1.4.1.9.9.46.1.3.1.1.2",
    "CISCO-VTP-MIB::vtpVlanName":             "1.3.6.1.4.1.9.9.46.1.3.1.1.4",
    "CISCO-VTP-MIB::vtpVlanType":             "1.3.6.1.4.1.9.9.46.1.3.1.1.3",
    # ── SNMPv2-SMI (enterprises / generic) ──────────────────────────────
    "SNMPv2-SMI::enterprises":            "1.3.6.1.4.1",
    "SNMPv2-SMI::mib-2":                  "1.3.6.1.2.1",
    "SNMPv2-SMI::transmission":           "1.3.6.1.2.1.10",
    "SNMPv2-SMI::experimental":           "1.3.6.1.3",
    # ── RFC1213-MIB (legacy MIB-II) ────────────────────────────────────
    "RFC1213-MIB::ifDescr":               "1.3.6.1.2.1.2.2.1.2",
    "RFC1213-MIB::ifType":                "1.3.6.1.2.1.2.2.1.3",
    "RFC1213-MIB::ifSpeed":               "1.3.6.1.2.1.2.2.1.5",
    "RFC1213-MIB::ifOperStatus":          "1.3.6.1.2.1.2.2.1.8",
    "RFC1213-MIB::ifInOctets":            "1.3.6.1.2.1.2.2.1.10",
    "RFC1213-MIB::ifOutOctets":           "1.3.6.1.2.1.2.2.1.16",
    "RFC1213-MIB::ipRouteDest":           "1.3.6.1.2.1.4.21.1.1",
    "RFC1213-MIB::ipRouteNextHop":        "1.3.6.1.2.1.4.21.1.7",
    "RFC1213-MIB::atPhysAddress":         "1.3.6.1.2.1.3.1.1.2",
}

# Build a reverse set of just the MODULE::name keys (without instance) for fast lookup
_OID_TABLE_KEYS = set(_OID_TABLE.keys())


# ---------------------------------------------------------------------------
# Regex for snmpwalk line format
# ---------------------------------------------------------------------------

# Captures the optional SNMP type tag (e.g. "STRING", "Counter32", "Timeticks")
_LINE_RE = re.compile(
    r"^(?:"
    r"(?P<module>[A-Za-z0-9_-]+)::(?P<name>[A-Za-z0-9_-]+)(?P<inst>(?:\.\d+)*)"
    r"|\.(?P<rawoid>[\d.]+)"
    r")"
    r"\s*=\s*"
    r"(?:(?P<typetag>[A-Za-z][A-Za-z0-9-]*\d*):\s*)?"   # optional "TYPE: " prefix — captured
    r"(?P<value>.+)$"
)

# Mapping from snmpwalk TYPE tag to WebNetLab value_type
_TYPE_MAP: dict[str, str] = {
    "STRING":      "string",
    "OID":         "string",
    "Hex-STRING":  "string",
    "Network Address": "string",
    "INTEGER":     "integer",
    "Counter32":   "counter",
    "Counter64":   "counter",
    "Gauge32":     "gauge",
    "Gauge64":     "gauge",
    "Timeticks":   "timeticks",
    "IpAddress":   "ipaddress",
    "BITS":        "string",
}

# ---------------------------------------------------------------------------
# pysnmp fallback (best-effort for MIBs not in the static table)
# ---------------------------------------------------------------------------

try:
    from pysnmp.smi import builder as _builder, view as _view, compiler as _compiler
    _mib_builder = _builder.MibBuilder()
    _compiler.addMibCompiler(_mib_builder, sources=["@mib@"])
    _mib_view = _view.MibViewController(_mib_builder)
    _HAS_PYSNMP = True
except Exception:
    _HAS_PYSNMP = False


def _resolve_symbolic(module: str, name: str, inst: str) -> str | None:
    """Resolve MODULE::name → numeric OID string, or return None if unresolvable.

    Resolution order:
    1. Static _OID_TABLE lookup (instant, covers 250+ common objects).
    2. pysnmp MIB engine (best-effort, only works for bundled MIBs).
    3. Return None — caller will skip the entry.
    """
    key = f"{module}::{name}"

    # ── 1. Static table ──────────────────────────────────────────────────
    base = _OID_TABLE.get(key)
    if base is not None:
        # Special case: sysUpTimeInstance is already the full OID including .0
        if key == "DISMAN-EVENT-MIB::sysUpTimeInstance":
            return base  # inst is always empty for this one
        return base + inst if inst else base

    # ── 2. pysnmp engine ─────────────────────────────────────────────────
    if _HAS_PYSNMP:
        try:
            from pysnmp.smi.rfc1902 import ObjectIdentity
            oid_obj = ObjectIdentity(module, name)
            oid_obj.resolveWithMib(_mib_view)
            numeric = str(oid_obj.getOid())
            return numeric + inst if inst else numeric
        except Exception:
            pass

    # ── 3. Unresolvable → skip ───────────────────────────────────────────
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Timeticks raw value looks like: "(14533823) 1 day, 16:22:18.23"
# We extract only the integer in parentheses.
_TIMETICKS_RE = re.compile(r"^\((\d+)\)")


def _normalize_value(raw: str, vtype: str) -> str:
    """Clean up the raw value string based on its detected type.

    - Timeticks: strip "(integer) human-readable" → just the integer string
    - STRING:    strip surrounding quotes already done by caller
    - others:    return as-is
    """
    if vtype == "timeticks":
        m = _TIMETICKS_RE.match(raw.strip())
        if m:
            return m.group(1)
        # If no parentheses, try to use just the first word if it's numeric
        first = raw.strip().split()[0] if raw.strip() else "0"
        return first if first.isdigit() else "0"
    return raw


def parse_snmpwalk(text: str) -> list[WalkEntry]:
    """Parse snmpwalk text output and return a list of WalkEntry(oid, value, value_type).

    Blank lines and comment lines (starting with #) are silently skipped.
    Lines that do not match the expected format are silently skipped.
    Lines whose OID cannot be resolved to a dotted-numeric form are skipped
    (they must not be stored as symbolic strings — that crashes the agent).

    The value_type is inferred from the snmpwalk TYPE tag (STRING, Counter32, etc.)
    and normalised to the WebNetLab vocabulary.  Timeticks values are stripped to
    their integer component so the agent can encode them correctly.
    """
    entries: list[WalkEntry] = []
    skipped_symbolic = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue

        raw_value = m.group("value").strip().strip('"')

        # Determine value_type from the captured type tag
        typetag  = (m.group("typetag") or "").strip()
        vtype    = _TYPE_MAP.get(typetag, "string")

        # Normalise the value (e.g. strip timeticks human text)
        value = _normalize_value(raw_value, vtype)

        if m.group("rawoid") is not None:
            oid = m.group("rawoid")
        else:
            oid = _resolve_symbolic(
                module=m.group("module"),
                name=m.group("name"),
                inst=m.group("inst") or "",
            )
            if oid is None:
                skipped_symbolic += 1
                continue

        if not is_numeric_oid(oid):
            skipped_symbolic += 1
            continue

        entries.append(WalkEntry(oid=oid, value=value, value_type=vtype))

    if skipped_symbolic:
        import logging
        logging.getLogger(__name__).debug(
            "parse_snmpwalk: skipped %d unresolvable symbolic OID(s)", skipped_symbolic
        )

    return entries
