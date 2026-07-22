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
    """A new 'First Last' name with independently-drawn first and last, unique within `used` if given.

    Run-local uniqueness ONLY — the surname comes from the fixed `_LAST_NAMES` pool, so a name it
    returns may well already exist in the passenger table. Use `fresh_pool()` when the set must be
    DB-absent (that is what the `name_uniqueness` checkpoint enforces)."""
    while True:
        name = f"{secrets.choice(_FIRST_NAMES)} {secrets.choice(_LAST_NAMES)}"
        if used is None or name not in used:
            if used is not None:
                used.add(name)
            return name


# ── DB-absent unique names ────────────────────────────────────────────────────────────────────
# The fixed `_LAST_NAMES` pool above holds 48 surnames — it is consumed within a couple of seeded
# sets, after which every "fresh" name already exists in the passenger table and the
# `name_uniqueness` checkpoint has nothing left to certify. Surnames are therefore GENERATED from
# realistic English toponymic syllables (prefix[+middle]+suffix), giving an effectively unlimited
# space, and filtered against the live DB at assignment time so a generated name never collides
# with an existing passenger. Ported from the reference pipeline's `crt_uniqnames.fresh_pool`.
_SURNAME_PREFIX = """Ash Black Bram Bren Bright Brook Cald Carl Chad Cliff Crest Dale Dun East Elder
Fair Fen Frost Gald Green Hart Haw Holl Iron Kes Kirk Lang Lark Long Marsh Mere Mill Moss North Oak
Oat Pen Rain Raven Red Ridge Rook Rush Sedge Sharp Silver Stan Stone Thorn Thistle Under West Whit
Wild Wind Wold Wolf Wood Wren Yar Ald Barn Bex Bly Cot Den Ever Gar Hal Hod Ives Lin Nether Ormer
Pres Quen Sel Tat Tut Ulls Vane Wex Yeo""".split()
_SURNAME_MIDDLE = ["", "", "", "er", "en", "ing", "le", "an", "el", "ow"]
_SURNAME_SUFFIX = """brook bury by combe cott croft dale den field ford gate grove ham hurst ley low
mere more ridge shaw stead ston thorpe ton wick wood worth wyn beck holt marsh pool vale""".split()


def generated_surnames(seed: int = 4242) -> list[str]:
    """Deterministically shuffled list of generated candidate surnames (5..12 chars, deduped)."""
    import random

    rng = random.Random(seed)
    out = []
    for p in _SURNAME_PREFIX:
        for m in _SURNAME_MIDDLE:
            for s in _SURNAME_SUFFIX:
                w = p + m + s
                if 5 <= len(w) <= 12 and w[-1] != w[0].lower():
                    out.append(w.capitalize())
    out = list(dict.fromkeys(out))  # dedup, preserve order
    rng.shuffle(out)
    return out


def fresh_pool(n: int, *, in_db=None, seed: int = 4242, batch: int = 800) -> list[tuple[str, str]]:
    """`n` (first, last) names whose surnames are all distinct AND absent from the passenger table.

    `in_db(batch) -> set[str]` returns which of the UPPERCASED surnames in `batch` already exist
    (see `source.surnames_present`). Omit it — or pass None — to skip DB filtering, which is what
    the offline tests do; the names are then merely distinct, not certified DB-absent.

    Raises RuntimeError if the generator cannot produce `n` DB-absent surnames, rather than
    silently handing back colliding names the checkpoint would later fail on."""
    import random

    rng = random.Random(seed)
    candidates = [s.upper() for s in generated_surnames(seed)]
    free: list[str] = []
    for i in range(0, len(candidates), batch):
        chunk = candidates[i:i + batch]
        taken = set(in_db(chunk)) if in_db else set()
        free.extend([s for s in chunk if s not in taken])
        if len(free) >= n:
            break
    if len(free) < n:
        raise RuntimeError(
            f"unique-name generator short: need {n}, produced {len(free)} DB-absent surnames")
    firsts = [f.upper() for f in _FIRST_NAMES]
    return [(rng.choice(firsts), free[i]) for i in range(n)]
