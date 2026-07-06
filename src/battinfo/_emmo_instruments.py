"""EMMO instrument classification shared by the resolver JSON-LD builder and publication.

Previously duplicated (identically) in ``battinfo.api`` and ``battinfo.publication``.
"""
from __future__ import annotations

from typing import Any

_INSTRUMENT_EMMO_MAP: dict[str, str] = {
    # Battery cyclers (galvanostatic instruments)
    "maccor": "BatteryCycler",
    "arbin": "BatteryCycler",
    "neware": "BatteryCycler",
    "landt": "BatteryCycler",
    "basytec": "BatteryCycler",
    "novonix": "BatteryCycler",
    "digatron": "BatteryCycler",
    # Biologic can be either, but VMP/MPG/SP lines are potentiostats/galvanostats
    "biologic": "Potentiostat",
    "vmp": "Potentiostat",
    "mpg": "Potentiostat",
    "sp-": "Potentiostat",
    "hcp": "Potentiostat",
    # Dedicated potentiostats / galvanostats
    "gamry": "Potentiostat",
    "autolab": "Potentiostat",
    "zahner": "Potentiostat",
    "ivium": "Potentiostat",
    "metrohm": "Potentiostat",
    "solartron": "Potentiostat",
    "galvanostat": "Galvanostat",
    "potentiostat": "Potentiostat",
    "cycler": "BatteryCycler",
}


def _instrument_emmo_type(name: str) -> str:
    """Return the EMMO equipment class for a test instrument name string."""
    lower = (name or "").lower()
    for keyword, emmo_class in _INSTRUMENT_EMMO_MAP.items():
        if keyword in lower:
            return emmo_class
    return "MeasuringInstrument"


def _instrument_node(name: str) -> dict[str, Any]:
    """Build an equipment node with EMMO type + schema.org name."""
    return {"@type": _instrument_emmo_type(name), "schema:name": name}
