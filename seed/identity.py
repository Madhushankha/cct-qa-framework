"""Fresh booking identity per seed run.

Every seed run mints a BRAND-NEW record locator (PNR) and an independent first/last name for each
case, instead of re-using the dataset's PNR. Re-seeding the same PNR into INT leaves the previous
run's trip-tracer row behind (a stale INACTIVE row alongside the new ACTIVE one); the chatbot's
booking lookup then can't resolve the PNR unambiguously and reports "I couldn't find a booking"
(observed on VNNOOV: 2 rows INACTIVE+ACTIVE, vs a cleanly-seeded PNR's single ACTIVE row). A fresh
locator each run sidesteps the collision entirely — one PNR, one trip row.

The dataset still supplies the SCENARIO (systemCode, verdict, amount, regime, route); only the
identity (locator + passenger name) is regenerated here. Locators are 6-char uppercase (airline
record-locator shape); names are drawn independently from first/last pools so first and last vary
per case. `secrets` gives good entropy; the small `used` guards keep a single run collision-free.
"""
from __future__ import annotations

import secrets

# record-locator alphabet: uppercase letters + unambiguous digits (no I/O/0/1), first char a letter —
# the 6-char alphanumeric shape airline PNRs use.
_LOC_FIRST = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOC_REST = _LOC_FIRST + "23456789"

_FIRST_NAMES = [
    "Percy", "Zora", "Joelle", "Annika", "Larissa", "Violeta", "Wesley", "Mateo", "Sven", "Nikolai",
    "Gareth", "Ingrid", "Tobias", "Marisol", "Dagny", "Rourke", "Priya", "Elias", "Camille", "Bjorn",
    "Odessa", "Cormac", "Sabine", "Thaddeus", "Freya", "Lorcan", "Anouk", "Silas", "Marnie", "Emil",
    "Rosalind", "Caspian", "Delphine", "Ambrose", "Yara", "Leopold", "Isolde", "Ronan", "Beatrix", "Otto",
    "Magnus", "Cordelia", "Fabian", "Linnea", "Soren", "Elowen", "Damaris", "Bartholomew", "Saskia", "Quentin",
]
_LAST_NAMES = [
    "Mossershaw", "Undercott", "Caldleley", "Oakingcombe", "Thornenlow", "Vaneingham", "Brightwater", "Hollingsby",
    "Ravenscar", "Fenwicke", "Dunmorrow", "Ashcombe", "Wexleigh", "Pemberton", "Harrowgate", "Stellenmark",
    "Crowhurst", "Blackwood", "Ellingham", "Marchetti", "Nordstrand", "Vasquez", "Lindqvist", "Fairholme",
    "Whitlocke", "Aldercott", "Bramblewood", "Coppersmith", "Darlington", "Everhart", "Fothergill", "Greenhalgh",
    "Hartwell", "Inglewood", "Kingsleigh", "Lockridge", "Merriweather", "Netherby", "Osgoode", "Prendergast",
    "Quillfeather", "Rutherglen", "Sackville", "Thistlewood", "Underhill", "Vanterpool", "Westenra", "Yardley",
]


def fresh_pnr(used: set | None = None) -> str:
    """A new 6-char uppercase record locator (first char a letter), unique within `used` if given."""
    while True:
        loc = secrets.choice(_LOC_FIRST) + "".join(secrets.choice(_LOC_REST) for _ in range(5))
        if used is None or loc not in used:
            if used is not None:
                used.add(loc)
            return loc


def fresh_name(used: set | None = None) -> str:
    """A new 'First Last' name with independently-drawn first and last, unique within `used` if given."""
    while True:
        name = f"{secrets.choice(_FIRST_NAMES)} {secrets.choice(_LAST_NAMES)}"
        if used is None or name not in used:
            if used is not None:
                used.add(name)
            return name
