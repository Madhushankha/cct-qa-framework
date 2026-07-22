#!/usr/bin/env python3
"""Shared passenger-name UNIQUENESS helper for all CRT/INT/BAT test-data pipelines.

Two jobs, used by every *_build.py and *_checkpoints.py:

  ASSIGN (build side):   fresh_pool(conn, n) -> n realistic [first,last] names whose SURNAMES are
                         all distinct AND absent from the passenger table. assign_names(records,
                         npax_of, conn) writes r['pax_names'] (one [first,last] per pax) + sets
                         r['uniq_names']=True so the checkpoint enforces it.

  CHECK (checkpoint side): name_uniqueness(conn, ids) -> (clean_count, offenders) where a PNR is an
                         offender if any of its passenger names repeats within the set OR already
                         exists on another PNR in the passenger table. Gate ENFORCEMENT on whether
                         the index rows carry uniq_names (else print as info) so legacy reused-name
                         sets don't retroactively fail.

Both build & checkpoint scripts just do:
    import crt_uniqnames as U
    ...  U.assign_names(records, npax_of, conn)          # build
    ...  clean, off = U.name_uniqueness(conn, ids)        # checkpoint
"""
import json, os, random

_HERE=os.path.dirname(os.path.abspath(__file__))
POOL_FILE=os.path.join(_HERE, "..", "scenarios", "fd-sit", "_FD_uniqnames_pool2.json")

# Surnames are GENERATED from realistic English toponymic syllables (prefix[+middle]+suffix) so the
# space is effectively unlimited — a fixed list gets consumed as each unique-name set lands in the DB.
# DB-absence is filtered at runtime, so generated names never collide with existing passengers.
_PRE="""Ash Black Bram Bren Bright Brook Cald Carl Chad Cliff Crest Dale Dun East Elder Fair Fen Frost
Gald Green Hart Haw Holl Iron Kes Kirk Lang Lark Long Marsh Mere Mill Moss North Oak Oat Pen Rain
Raven Red Ridge Rook Rush Sedge Sharp Silver Stan Stone Thorn Thistle Under West Whit Wild Wind Wold
Wolf Wood Wren Yar Ald Barn Bex Bly Cot Den Ever Gar Hal Hod Ives Lin Nether Ormer Pres Quen Sel
Tat Tut Ulls Vane Wex Yeo""".split()
_MID=["", "", "", "er", "en", "ing", "le", "an", "el", "ow"]
_SUF="""brook bury by combe cott croft dale den field ford gate grove ham hurst ley low mere more
ridge shaw stead ston thorpe ton wick wood worth wyn beck holt marsh pool ridge vale""".split()
_FIRST="""Adrian Brenna Callum Delphine Eamon Fiona Gareth Heidi Ivano Joelle Kenji Larissa Mateo
Nadezhda Orson Priya Quentin Rosalind Sven Tamsin Ulrich Violeta Wesley Ximena Yannick Zora
Annika Bodhi Cedrick Dagny Elias Freya Gideon Hallie Isolde Jasper Kira Lorcan Mirabel Nikolai
Oona Percy Romilly Sebastian Theodora Umberto Vesna Winslow Yardley Zephyr""".split()

def _norm(s): return s.strip().upper()

def _gen_surnames(seed):
    """Deterministically generate a large shuffled list of realistic candidate surnames."""
    rng=random.Random(seed); out=[]
    for p in _PRE:
        for m in _MID:
            for s in _SUF:
                w=p+m+s
                if 5 <= len(w) <= 12 and w[-1]!=w[0].lower(): out.append(w.capitalize())
    out=list(dict.fromkeys(out))          # dedup, preserve order
    rng.shuffle(out)
    return out

def _mk_cur(cur_or_conn):
    """Accept either a psycopg2 cursor or connection; return a usable cursor."""
    return cur_or_conn.cursor() if hasattr(cur_or_conn,"cursor") else cur_or_conn

def fresh_pool(cur_or_conn, n, seed=4242):
    """Return n [first,last] names: all surnames distinct AND absent from passenger.last_name.
    Surnames are generated + DB-filtered in batches, so the space never exhausts across runs.
    Accepts a cursor OR a connection."""
    cur=_mk_cur(cur_or_conn); cand=[_norm(s) for s in _gen_surnames(seed)]
    free=[]; B=800
    for i in range(0, len(cand), B):
        batch=cand[i:i+B]
        cur.execute("select distinct last_name from passenger where last_name = any(%s)", (batch,))
        indb={r[0] for r in cur.fetchall()}
        free.extend([s for s in batch if s not in indb])
        if len(free) >= n: break
    if len(free) < n:
        raise RuntimeError(f"unique-name generator short: need {n}, produced {len(free)} DB-absent surnames")
    rng=random.Random(seed); firsts=[_norm(f) for f in _FIRST]
    return [[rng.choice(firsts), free[i]] for i in range(n)]

def assign_names(records, npax_of, cur_or_conn, seed=4242):
    """Assign unique DB-absent names to every passenger of every record.
    records: list of dicts (mutated: r['pax_names'], r['pax'], r['uniq_names']=True).
    npax_of: callable(record)->int passenger count for that record. Accepts cursor OR connection."""
    counts=[npax_of(r) for r in records]; total=sum(counts)
    pool=fresh_pool(cur_or_conn, total, seed=seed); k=0
    for r,c in zip(records, counts):
        names=[list(pool[k+j]) for j in range(c)]; k+=c
        r["pax_names"]=names
        r["pax"]=f"{names[0][0]} {names[0][1]}"
        r["uniq_names"]=True
    return total

def apply_to_scenario(scn, record):
    """Build side: overwrite scenario passenger names from record['pax_names'] (wins over canonical)."""
    pn=record.get("pax_names")
    if not pn: return scn
    for j,p in enumerate(scn.get("passengers", [])):
        if j < len(pn): p["first_name"], p["last_name"] = pn[j]
    return scn

def name_uniqueness(cur_or_conn, ids):
    """Checkpoint side: return (clean_count, offenders).
    A PNR offends if any of its passenger names repeats within the set OR already exists on
    another PNR in the passenger table. Accepts a cursor OR a connection."""
    from collections import Counter
    cur=_mk_cur(cur_or_conn)
    cur.execute("SELECT pnr_id, first_name, last_name FROM passenger WHERE pnr_id=ANY(%s) AND NOT is_removed",(ids,))
    rows=cur.fetchall()
    within=Counter((f,l) for _,f,l in rows)
    within_dup={pair for pair,c in within.items() if c>1}
    uniq_pairs=list({(f,l) for _,f,l in rows})
    ext=set()
    if uniq_pairs:
        cur.execute("SELECT DISTINCT first_name,last_name FROM passenger WHERE (first_name,last_name) IN %s AND NOT (pnr_id=ANY(%s))",(tuple(uniq_pairs),ids))
        ext={(f,l) for f,l in cur.fetchall()}
    offenders=sorted({pid for pid,f,l in rows if (f,l) in within_dup or (f,l) in ext})
    return len(ids)-len(offenders), offenders

def print_check(conn, ids, rows):
    """Convenience for checkpoint scripts. Prints the line, returns True if it should fail the audit.
    Enforced only when any index row carries uniq_names; else printed as (info)."""
    clean, off = name_uniqueness(conn, ids)
    enforce = any(m.get("uniq_names") for m in rows)
    label = "name uniqueness" if enforce else "name uniq (info)"
    print(f"  {label:18} {clean}/{len(ids)}"+("" if not off else f"  DUP/INDB {len(off)}: {off[:8]}"))
    return bool(off) and enforce

if __name__=="__main__":
    print("crt_uniqnames helper — pool surnames:", len(set(_norm(s) for s in _SURNAMES)), "first names:", len(_FIRST))
