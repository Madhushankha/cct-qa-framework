#!/usr/bin/env python3
"""Build Baggage CRT set-7 — one set, reusing the sets4/5 driver logic.

Contact (via CRT_EMAIL/CRT_PHONE env, read by bag_crt_build):
  email = lahiru@ae-qa1-aircanada.mailinator.com   phone = +94712534323 (lahiru phone)
Unique DB-absent names (disjoint from sets 1-6, already in the passenger table).

Usage: CRT_EMAIL=... CRT_PHONE=... AWS_PROFILE=ac-cct-crt python3 bag_build_set7.py
"""
import bag_build_sets45 as D

D.TODAY = "2026-07-20"
s = dict(name="set7", seed="616161", tprefix="014311",
         out=f"{D.WORK}/_BAG_crt_index_set7.json")
ok = D.build(s)
print("\nSET7_DONE ok=" + str(ok))
