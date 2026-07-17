"""NON-MVP (Intent Routing) — routing-target reader. There is NO per-case seed for this feed.

Non-MVP tests pure chat intent-routing: given a stated intent, does the agent sort it into the right
category and route it to the right destination —

    Claims Dashboard | Live Agent Handoff | FAQ | Manual Handling

Nothing is published to Kafka and no DDS is pinned. The ONLY precondition is that a valid POOL PNR
exists to identify against, and the SAME pool PNR works for every case (see
docs/superpowers/plans/2026-07-17-nonmvp-seed.md and data/seed-templates/nonmvp/README.md).

So the "seed" for Non-MVP is not data — it is reading the EXPECTED routing target out of each case's
gap-doc title (e.g. "Baggage Damage - Post-Travel - Claims Dashboard (BG)", "Joining Aeroplan - All
Travel States - FAQ Only", "Denied Boarding - No Booking - N/A Handling"). This module does that so a
router auditor can compare the agent's chosen destination against the expected one.

Pure functions only — offline-testable.
"""
from __future__ import annotations

import re

# The routing-destination enum — mirrors core/registry/feeds/nonmvp.yaml judge.verdict_enum.
DESTINATIONS = ("CLAIMS_DASHBOARD", "LIVE_AGENT", "FAQ", "MANUAL_HANDLING",
                "NO_DETERMINATION", "UNKNOWN")

# NON-MVP never needs a per-case seed. Exposed as a constant so a runner can branch on it.
NEEDS_SEED = False

# Trailing-paren category codes used in the titles: (BG) baggage, (CR) customer relations,
# (RS) refund services, (TO) topline/aeroplan, (CC) contact centre / pre-travel live agent.
_CATEGORY_RE = re.compile(r"\(([A-Z]{2})\)")


def needs_seed(uc=None) -> bool:
    """Non-MVP needs no per-case seed data — always False. Present so callers can treat every feed
    uniformly (`if feed_module.needs_seed(uc): ...`)."""
    return NEEDS_SEED


def intent_category(uc) -> str:
    """The intent-category code the title tags (BG/CR/RS/TO/CC), or '' if none. This is the ANC/FD
    `system_code` analogue for Non-MVP — the judge matches routing_target against `status` and this
    against `system_code` (see nonmvp.yaml)."""
    codes = _CATEGORY_RE.findall(getattr(uc, "title", "") or "")
    return codes[-1] if codes else ""


def otp_required(uc):
    """Tri-state OTP requirement from the title: False if "OTP Not Required", None if "OTP TBD",
    else True (identification/OTP is the default before a case is opened)."""
    t = (getattr(uc, "title", "") or "").lower()
    if "otp not required" in t:
        return False
    if "otp tbd" in t:
        return None
    return True


def travel_state_dependent(uc) -> bool:
    """True when the routing target depends on travel state — the title names BOTH a pre-travel and a
    post-travel destination, or explicitly says the routing is travel-state-dependent."""
    t = (getattr(uc, "title", "") or "").lower()
    if "travel-state-dependent" in t or "travel state" in t or "all travel states" in t:
        return True
    return "pre-travel" in t and "post-travel" in t


def routing_target(uc) -> str:
    """The EXPECTED routing destination for `uc`, read from the title.

    Precedence (most specific / most terminal first):
      1. FAQ Only / FAQ            -> FAQ        (answer first, no case, no live agent)
      2. N/A Handling              -> NO_DETERMINATION  (e.g. no booking to route)
      3. Must-Not-Route-to-Auto /
         Manual Handling           -> MANUAL_HANDLING
      4. Claims Dashboard          -> CLAIMS_DASHBOARD  (the post-travel default; wins over a
                                      co-mentioned pre-travel Live Agent, which is the pre-travel
                                      branch surfaced separately via routing_of()['pre_travel'])
      5. Live Agent                -> LIVE_AGENT
      6. otherwise                 -> UNKNOWN
    """
    t = (getattr(uc, "title", "") or "").lower()
    if "faq only" in t or "faq" in t:
        return "FAQ"
    if "n/a handling" in t or "n/a" in t:
        return "NO_DETERMINATION"
    if "must not be routed" in t or "manual handling" in t or "manual flow" in t:
        return "MANUAL_HANDLING"
    if "claims dashboard" in t:
        return "CLAIMS_DASHBOARD"
    if "live agent" in t or "lah" in t:
        return "LIVE_AGENT"
    return "UNKNOWN"


def _pre_post_targets(uc) -> tuple[str, str]:
    """For a travel-state-dependent title, split the pre-travel vs post-travel destination. The
    titles use the form "Pre-Travel Live Agent (CC) / Post-Travel Claims Dashboard (CR)"."""
    t = (getattr(uc, "title", "") or "")
    pre = post = ""
    m = re.search(r"pre-travel\s+([a-z /&]+?)(?:\(|/|$)", t, re.IGNORECASE)
    if m and "live agent" in m.group(1).lower():
        pre = "LIVE_AGENT"
    elif m and "claims dashboard" in m.group(1).lower():
        pre = "CLAIMS_DASHBOARD"
    m = re.search(r"post-travel\s+([a-z /&]+?)(?:\(|/|$)", t, re.IGNORECASE)
    if m and "claims dashboard" in m.group(1).lower():
        post = "CLAIMS_DASHBOARD"
    elif m and "live agent" in m.group(1).lower():
        post = "LIVE_AGENT"
    return pre, post


def routing_of(uc) -> dict:
    """The full routing verdict for `uc`: the primary destination, the intent category, OTP
    requirement, and — for travel-state-dependent cases — the pre/post-travel split. This is the
    Non-MVP analogue of anc_refund.build_refund_response / dds_pin verdict extraction: a structured
    expected-outcome record a router auditor compares the agent's choice against."""
    pre, post = _pre_post_targets(uc)
    return {
        "case_id": getattr(uc, "id", ""),
        "destination": routing_target(uc),
        "intent_category": intent_category(uc),
        "otp_required": otp_required(uc),
        "travel_state_dependent": travel_state_dependent(uc),
        "pre_travel": pre or None,
        "post_travel": post or None,
        "needs_seed": NEEDS_SEED,
    }
