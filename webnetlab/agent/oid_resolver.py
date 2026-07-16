"""
oid_resolver.py — Converts a raw Redis JSON entry into an SNMP response value.

Each entry stored in Redis under device:{id}:oids is a JSON string:

    {"mode": "static",  "value": "GigabitEthernet0/0", "type": "string"}
    {"mode": "static",  "value": "1",                  "type": "integer"}
    {"mode": "random",  "config": {"min":0,"max":4294967295,"type":"counter"}}
    {"mode": "scripted","script": "int(time.time())%100000", "type": "timeticks"}

Supported types: string (default), integer, counter, gauge, timeticks, ipaddress
"""

import json
import time
import random


def resolve_oid_value(raw_json: str) -> tuple:
    """
    Return (python_value, snmp_type_hint) where snmp_type_hint is one of:
        "string", "integer", "counter", "gauge", "timeticks", "ipaddress"

    The caller uses the type hint to pick the correct ASN.1 class.
    """
    entry = json.loads(raw_json)
    mode  = entry.get("mode", "static")
    vtype = entry.get("type", "string")   # default: string

    if mode in ("static", "walk_seed"):
        raw = entry.get("value", "")
        return (_coerce(raw, vtype), vtype)

    if mode == "random":
        cfg   = entry.get("config", {})
        lo    = cfg.get("min", 0)
        hi    = cfg.get("max", 100)
        rtype = cfg.get("type", "integer")   # counter | gauge | integer
        return (random.randint(lo, hi), rtype)

    if mode == "scripted":
        script = entry.get("script", "0")
        try:
            val = eval(  # noqa: S307
                script,
                {"__builtins__": {}},
                {"time": time, "random": random},
            )
        except Exception:
            val = 0
        return (val, vtype)

    return ("", "string")


def _coerce(value: str, vtype: str):
    """Convert a stored string value to the appropriate Python type."""
    if vtype in ("integer", "counter", "gauge", "timeticks"):
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
    return str(value) if value is not None else ""
