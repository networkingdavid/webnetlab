"""
MIB compilation and OID tree extraction service.

Uses pysmi to compile uploaded MIB text files into a Python object model,
then walks the result to produce a flat list of OID nodes that the API
can store and serve to the frontend.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import PyPackageSearcher, StubSearcher
from pysmi.writer import CallbackWriter
from pysmi.parser.smi import parserFactory
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.compiler import MibCompiler

# Directory where user-uploaded MIB files live (volume-mounted in Docker)
MIB_STORE = Path(os.environ.get("MIB_STORE", "/app/mibs"))

# Remote source for standard IETF/IANA MIBs (used when not in local store)
_PYSNMP_MIB_REPO = "https://mibs.pysnmp.com/asn1/@mib@"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_compiler(extra_search_dirs: list[str] | None = None) -> tuple[MibCompiler, dict[str, str]]:
    """Return a (compiler, output_store) pair.

    The compiler writes compiled Python text into *output_store* via a
    ``CallbackWriter`` so nothing hits disk.

    Search order:
    1. Uploaded MIBs in MIB_STORE
    2. Any extra_search_dirs (e.g. containing the just-uploaded file)
    3. HTTP fetch from mibs.pysnmp.com as fallback for standard IETF/IANA MIBs
    4. pysnmp's built-in compiled MIBs (searched so already-compiled deps are skipped)
    5. StubSearcher for ASN.1 built-ins (ASN1, ASN1-ENUMERATION, ASN1-REFINEMENT)
    """
    output_store: dict[str, str] = {}

    def _capture(mib_name: str, text: str, _cbCtx: Any) -> None:  # noqa: N803
        output_store[mib_name] = text

    cg = PySnmpCodeGen()
    compiler = MibCompiler(parserFactory()(), cg, CallbackWriter(_capture))

    # File sources
    for d in ([str(MIB_STORE)] + (extra_search_dirs or [])):
        if os.path.isdir(d):
            compiler.add_sources(FileReader(d))

    # HTTP fallback for standard MIBs
    compiler.add_sources(HttpReader(_PYSNMP_MIB_REPO))

    # Searchers: pysnmp's pre-compiled package covers most IETF MIBs
    compiler.add_searchers(PyPackageSearcher("pysnmp.smi.mibs"))

    # Stub searcher for pysmi ASN.1 pseudo-MIBs (never need actual source)
    compiler.add_searchers(StubSearcher(*cg.fakeMibs))

    return compiler, output_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_mib(filepath: str, mib_name: str) -> dict[str, str]:
    """Compile *filepath* with pysmi and return a ``{mib_name: python_text}`` dict.

    Raises
    ------
    ValueError
        If pysmi reports a parse / compile error, or if a required dependency
        MIB is missing.
    """
    compiler, output_store = _build_compiler(
        extra_search_dirs=[str(Path(filepath).parent)]
    )

    try:
        status_map = compiler.compile(mib_name)
    except Exception as exc:
        raise ValueError(f"pysmi compiler raised an exception: {exc}") from exc

    # Collect missing dependencies before checking the primary MIB status
    missing = [name for name, st in status_map.items() if str(st) == "missing"]
    failed = [name for name, st in status_map.items() if str(st) == "failed"]

    if missing:
        raise ValueError(f"missing_dependency: {missing}")
    if failed:
        raise ValueError(f"pysmi failed to compile: {failed}")

    if not output_store:
        raise ValueError(
            f"pysmi produced no output for '{mib_name}'. "
            "Check that the file is a valid SMI MIB."
        )

    return output_store


# ---------------------------------------------------------------------------
# OID tree extraction
# ---------------------------------------------------------------------------

# pysmi emits one of two patterns for OID-bearing objects:
#
#  Pattern A — direct assignment (e.g. for simple scalars / identities):
#    ifMIB = ModuleIdentity(
#        (1, 3, 6, 1, 2, 1, 31),
#    )
#
#  Pattern B — type-aliased assignment (most table columns / scalars):
#    _IfIndex_Object = MibTableColumn
#    ifIndex = _IfIndex_Object(
#        (1, 3, 6, 1, 2, 1, 2, 2, 1, 1),
#        _IfIndex_Type()
#    )
#    ifIndex.setMaxAccess("read-only")
#
# We also want to capture:
#    ifIndex.setDescription("...")

_MIB_TYPES = {
    "MibScalar", "MibTable", "MibTableRow", "MibTableColumn",
    "MibIdentifier", "NotificationType", "ObjectIdentity", "ModuleIdentity",
}

# Maps private alias like `_IfIndex_Object` → its MIB type
_ALIAS_RE = re.compile(
    r"^(_\w+_Object)\s*=\s*("
    + "|".join(_MIB_TYPES)
    + r")\s*$",
    re.MULTILINE,
)

# Matches:   name = SomeCallable(
#                (1, 3, 6, 1, ...),
# The OID tuple follows as the first positional argument.
_ASSIGN_RE = re.compile(
    r"^(?P<name>[a-zA-Z]\w*)\s*=\s*(?P<cls>\w+)\s*\(\s*\n\s*\((?P<oid>[\d,\s]+)\)",
    re.MULTILINE,
)

_ACCESS_RE = re.compile(r'(\w+)\.setMaxAccess\("(?P<access>[^"]+)"\)')
_DESC_RE = re.compile(r'(\w+)\.setDescription\("(?P<desc>[^"]+)"\)')
_STATUS_RE = re.compile(r'(\w+)\.setStatus\("(?P<status>[^"]+)"\)')
_MODULE_ID_RE = re.compile(r"^(\w+)\s*=\s*ModuleIdentity\(", re.MULTILINE)


def extract_oid_tree(compiled_mib_text: str) -> list[dict]:
    """Parse pysmi-compiled Python source and return a flat sorted OID node list.

    Each node::

        {
            "name":        str,   # symbolic name  e.g. "ifIndex"
            "oid":         str,   # dotted OID     e.g. "1.3.6.1.2.1.2.2.1.1"
            "syntax":      str,   # type string
            "access":      str,   # e.g. "read-only"
            "description": str,
            "module":      str,   # MIB module name (ModuleIdentity object name)
        }
    """
    text = compiled_mib_text

    # Determine module name (name of the ModuleIdentity object)
    module_name = ""
    m = _MODULE_ID_RE.search(text)
    if m:
        module_name = m.group(1)

    # Build alias → MIB type map
    alias_map: dict[str, str] = {m.group(1): m.group(2) for m in _ALIAS_RE.finditer(text)}

    # Build per-symbol access / description / status maps
    access_map: dict[str, str] = {m.group(1): m.group("access") for m in _ACCESS_RE.finditer(text)}
    desc_map: dict[str, str] = {m.group(1): m.group("desc") for m in _DESC_RE.finditer(text)}

    nodes: list[dict] = []
    seen: set[str] = set()

    for m in _ASSIGN_RE.finditer(text):
        name = m.group("name")
        cls = m.group("cls")
        raw_oid = m.group("oid").strip().rstrip(",")

        # Resolve class: either a direct MIB type or an alias
        resolved_cls = alias_map.get(cls, cls)
        if resolved_cls not in _MIB_TYPES and cls not in _MIB_TYPES:
            continue

        if name in seen:
            continue
        seen.add(name)

        # Convert OID tuple to dotted string
        oid_str = ".".join(p.strip() for p in raw_oid.split(",") if p.strip())

        # Syntax: the alias without _Object suffix gives us the type
        # e.g. `_IfIndex_Object` → type alias `_IfIndex_Type` → resolved in type assignments
        # For a simpler approach: use the resolved class name as syntax for scalars
        syntax = resolved_cls

        nodes.append({
            "name": name,
            "oid": oid_str,
            "syntax": syntax,
            "access": access_map.get(name, ""),
            "description": desc_map.get(name, ""),
            "module": module_name,
        })

    nodes.sort(key=lambda n: _oid_sort_key(n["oid"]))
    return nodes


def _oid_sort_key(oid: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in oid.split(".") if x.isdigit())
    except Exception:
        return ()


# ---------------------------------------------------------------------------
# High-level entry points
# ---------------------------------------------------------------------------

def parse_mib_file(filepath: str) -> list[dict]:
    """Compile *filepath* and extract its OID tree.

    Returns the OID node list on success.
    On error returns a list with a single error-sentinel dict::

        [{"error": "...", "details": "..."}]
    """
    mib_name = Path(filepath).stem
    try:
        output_store = compile_mib(filepath, mib_name)
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("missing_dependency:"):
            import ast as _ast
            try:
                missing = _ast.literal_eval(msg.split(":", 1)[1].strip())
            except Exception:
                missing = [msg]
            return [{"error": "missing_dependency", "missing": missing, "details": msg}]
        return [{"error": msg, "details": ""}]
    except Exception as exc:  # noqa: BLE001
        return [{"error": "compilation_failed", "details": str(exc)}]

    # Use the primary MIB's compiled output (output_store may also contain deps)
    primary_text = output_store.get(mib_name) or next(iter(output_store.values()), "")
    if not primary_text:
        return [{"error": "empty_output", "details": "pysmi returned no compiled text"}]

    oids = extract_oid_tree(primary_text)
    if not oids:
        return [{"error": "no_oids_extracted", "details": "Compilation succeeded but no OID nodes found"}]

    return oids


def save_oid_tree(mib_name: str, oids: list[dict]) -> str:
    """Write *oids* as a JSON sidecar to ``{MIB_STORE}/{mib_name}_oids.json``.

    Returns the absolute path to the sidecar file.
    """
    MIB_STORE.mkdir(parents=True, exist_ok=True)
    sidecar_path = MIB_STORE / f"{mib_name}_oids.json"
    sidecar_path.write_text(json.dumps(oids, indent=2))
    return str(sidecar_path)


def load_oid_tree(sidecar_path: str) -> list[dict]:
    """Load OID tree from a JSON sidecar file."""
    return json.loads(Path(sidecar_path).read_text())
