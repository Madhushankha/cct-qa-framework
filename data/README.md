# data — gap docs & datasets (inputs)

This folder holds (or references) the **inputs** the framework consumes — it produces nothing itself.
The gap docs are the source of truth (see [`../catalog/README.md`](../catalog/README.md)).

## What lives here
- **Gap-analysis docs** per feed (`*_Miro_Gap_Analysis*.html`) — the canonical use-case + checkpoint catalogs.
- **Datasets / "executable" SIT HTMLs** — the same card/datagrid shape bound to concrete seeded PNRs.

## Layout (proposed)
```
data/
├── gap-docs/
│   ├── fd/            FD_UAT_Miro_Gap_Analysis*.html
│   ├── soc/           SOC_Miro_Gap_Analysis.html
│   ├── nc/  anc/  baggage/  seatchange/  bookingchange/  nonmvp/
└── datasets/          per-feed dataset HTML/CSV (the FD_ALL239_*, All_Data/** bundles)
```

## Sources (in the current project — copy or symlink, don't fork logic)
- `../../cct-qa-1/doc/source/**` — all the gap docs + `All_Data/**` dataset bundles.
- `../../cct-qa-1/fd-int-flow/src/FD_UAT_Miro_Gap_Analysis 18.html` — the FD gap doc.
- `../../cct-qa-1/CCT_Agent_New 2/` — reference SIT specs + executable HTMLs.

## Note
Only `{email, phone}` is supplied at runtime — **never** stored here. Contact info is injected during
seeding (P2), not part of any dataset. Ignore `__MACOSX/._*` resource-fork junk.
