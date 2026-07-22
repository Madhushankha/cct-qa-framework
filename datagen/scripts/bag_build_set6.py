#!/usr/bin/env python3
"""Build Baggage CRT set-6 — reuses the sets4/5 driver logic for ONE set.

Contact override (via CRT_EMAIL/CRT_PHONE env, read by bag_crt_build):
  email = lahiru.premathilake@aircanada.ca   phone = +94712534323 (lahiru phone)
Unique DB-absent names (disjoint from sets 1-5, which are already in the passenger table).

Usage: CRT_EMAIL=... CRT_PHONE=... AWS_PROFILE=ac-cct-crt python3 bag_build_set6.py
"""
import bag_build_sets45 as D

D.TODAY = "2026-07-17"
s = dict(name="set6", seed="969696", tprefix="014310",
         out=f"{D.WORK}/_BAG_crt_index_set6.json")
ok = D.build(s)
print("\nSET6_DONE ok=" + str(ok))
