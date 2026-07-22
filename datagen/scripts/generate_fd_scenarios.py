#!/usr/bin/env python3
"""
Generate FD SIT PNR Scenarios for all 132 test cases.
Creates JSON scenario files that can be published to Kafka.
"""

import json
import os
from datetime import datetime, timedelta

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios", "fd-sit")
os.makedirs(SCENARIOS_DIR, exist_ok=True)

# Base dates
BASE_DATE = "2026-06-25"
BOOKING_DATE = "2026-06-01"

# Passenger name bank (unique for each scenario)
PASSENGERS = [
    ("EMILY", "THOMPSON", "FEMALE", "1985-03-15"),
    ("MICHAEL", "CHEN", "MALE", "1978-07-22"),
    ("SARAH", "WILLIAMS", "FEMALE", "1990-11-08"),
    ("JAMES", "HARRISON", "MALE", "1965-04-30"),
    ("MARIE", "DUBOIS", "FEMALE", "1982-09-12"),
    ("DAVID", "COHEN", "MALE", "1975-06-18"),
    ("ROBERT", "JOHNSON", "MALE", "1988-02-28"),
    ("PATRICIA", "MARTIN", "FEMALE", "1992-01-25"),
    ("WILLIAM", "BROWN", "MALE", "1970-04-18"),
    ("JENNIFER", "TAYLOR", "FEMALE", "1995-08-05"),
    ("RICHARD", "ANDERSON", "MALE", "1968-12-10"),
    ("LINDA", "THOMAS", "FEMALE", "1983-05-20"),
    ("CHARLES", "JACKSON", "MALE", "1977-10-15"),
    ("BARBARA", "WHITE", "FEMALE", "1991-07-03"),
    ("JOSEPH", "HARRIS", "MALE", "1986-03-28"),
    ("SUSAN", "CLARK", "FEMALE", "1979-11-22"),
    ("THOMAS", "LEWIS", "MALE", "1972-08-14"),
    ("JESSICA", "ROBINSON", "FEMALE", "1994-04-09"),
    ("CHRISTOPHER", "WALKER", "MALE", "1981-01-17"),
    ("NANCY", "HALL", "FEMALE", "1987-06-25"),
    ("DANIEL", "ALLEN", "MALE", "1974-09-30"),
    ("KAREN", "YOUNG", "FEMALE", "1989-02-14"),
    ("MATTHEW", "KING", "MALE", "1976-12-05"),
    ("BETTY", "WRIGHT", "FEMALE", "1984-07-19"),
    ("ANTHONY", "SCOTT", "MALE", "1969-05-08"),
    ("MARGARET", "GREEN", "FEMALE", "1993-10-27"),
    ("MARK", "BAKER", "MALE", "1980-03-12"),
    ("SANDRA", "ADAMS", "FEMALE", "1971-08-21"),
    ("DONALD", "NELSON", "MALE", "1966-11-16"),
    ("ASHLEY", "HILL", "FEMALE", "1996-04-03"),
    ("STEVEN", "RAMIREZ", "MALE", "1973-07-29"),
    ("KIMBERLY", "CAMPBELL", "FEMALE", "1988-01-11"),
    ("PAUL", "MITCHELL", "MALE", "1967-06-24"),
    ("DONNA", "ROBERTS", "FEMALE", "1985-09-18"),
    ("ANDREW", "CARTER", "MALE", "1978-02-07"),
    ("CAROL", "PHILLIPS", "FEMALE", "1990-05-31"),
    ("JOSHUA", "EVANS", "MALE", "1982-10-22"),
    ("MICHELLE", "TURNER", "FEMALE", "1975-03-09"),
    ("KENNETH", "TORRES", "MALE", "1970-07-15"),
    ("AMANDA", "PARKER", "FEMALE", "1992-12-28"),
    ("KEVIN", "COLLINS", "MALE", "1983-04-06"),
    ("DOROTHY", "EDWARDS", "FEMALE", "1968-08-17"),
    ("BRIAN", "STEWART", "MALE", "1979-11-03"),
    ("MELISSA", "SANCHEZ", "FEMALE", "1986-02-21"),
    ("GEORGE", "MORRIS", "MALE", "1964-09-14"),
    ("DEBORAH", "ROGERS", "FEMALE", "1991-06-08"),
    ("EDWARD", "REED", "MALE", "1977-01-26"),
    ("STEPHANIE", "COOK", "FEMALE", "1984-04-19"),
    ("RONALD", "MORGAN", "MALE", "1971-10-11"),
    ("REBECCA", "BELL", "FEMALE", "1989-07-24"),
    ("TIMOTHY", "MURPHY", "MALE", "1976-03-17"),
    ("SHARON", "BAILEY", "FEMALE", "1981-08-30"),
    ("JASON", "RIVERA", "MALE", "1973-12-05"),
    ("LAURA", "COOPER", "FEMALE", "1987-05-13"),
    ("JEFFREY", "RICHARDSON", "MALE", "1969-09-27"),
    ("CYNTHIA", "COX", "FEMALE", "1994-02-09"),
    ("RYAN", "HOWARD", "MALE", "1980-06-22"),
    ("KATHLEEN", "WARD", "FEMALE", "1972-11-15"),
    ("JACOB", "TORRES", "MALE", "1985-04-28"),
    ("AMY", "PETERSON", "FEMALE", "1978-08-04"),
    ("GARY", "GRAY", "MALE", "1966-01-19"),
    ("ANGELA", "RAMIREZ", "FEMALE", "1990-10-07"),
    ("NICHOLAS", "JAMES", "MALE", "1982-05-25"),
    ("BRENDA", "WATSON", "FEMALE", "1975-12-31"),
    ("ERIC", "BROOKS", "MALE", "1988-03-14"),
    ("EMMA", "KELLY", "FEMALE", "1993-07-08"),
    ("JONATHAN", "SANDERS", "MALE", "1970-09-21"),
    ("VIRGINIA", "PRICE", "FEMALE", "1984-02-16"),
    ("STEPHEN", "BENNETT", "MALE", "1977-06-10"),
    ("CATHERINE", "WOOD", "FEMALE", "1981-11-28"),
    ("LARRY", "BARNES", "MALE", "1968-04-05"),
    ("CHRISTINE", "ROSS", "FEMALE", "1986-08-23"),
    ("JUSTIN", "HENDERSON", "MALE", "1974-01-30"),
    ("MARIE", "COLEMAN", "FEMALE", "1991-05-17"),
    ("SCOTT", "JENKINS", "MALE", "1979-10-09"),
    ("JANET", "PERRY", "FEMALE", "1983-03-26"),
    ("BRANDON", "POWELL", "MALE", "1971-07-12"),
    ("FRANCES", "LONG", "FEMALE", "1989-12-04"),
    ("BENJAMIN", "PATTERSON", "MALE", "1976-05-29"),
    ("ANN", "HUGHES", "FEMALE", "1992-09-15"),
    ("SAMUEL", "FLORES", "MALE", "1967-02-22"),
    ("DIANE", "WASHINGTON", "FEMALE", "1980-06-07"),
    ("GREGORY", "BUTLER", "MALE", "1973-11-19"),
    ("RUTH", "SIMMONS", "FEMALE", "1987-04-12"),
    ("ALEXANDER", "FOSTER", "MALE", "1969-08-25"),
    ("MARIA", "GONZALES", "FEMALE", "1994-01-08"),
    ("FRANK", "BRYANT", "MALE", "1982-05-03"),
    ("HELEN", "ALEXANDER", "FEMALE", "1975-09-28"),
    ("PATRICK", "RUSSELL", "MALE", "1978-12-14"),
    ("SAMANTHA", "GRIFFIN", "FEMALE", "1985-03-21"),
    ("RAYMOND", "DIAZ", "MALE", "1970-07-06"),
    ("KATHERINE", "HAYES", "FEMALE", "1988-10-31"),
    ("JACK", "MYERS", "MALE", "1972-02-18"),
    ("DEBRA", "FORD", "FEMALE", "1981-06-09"),
    ("DENNIS", "HAMILTON", "MALE", "1966-09-24"),
    ("RACHEL", "GRAHAM", "FEMALE", "1990-01-15"),
    ("JERRY", "SULLIVAN", "MALE", "1977-04-30"),
    ("CAROLYN", "WALLACE", "FEMALE", "1983-08-12"),
    ("TYLER", "WOODS", "MALE", "1974-11-27"),
    ("JANET", "WEST", "FEMALE", "1986-03-05"),
    ("AARON", "COLE", "MALE", "1968-06-18"),
    ("OLIVIA", "HUNT", "FEMALE", "1991-09-22"),
    ("JOSE", "MENDEZ", "MALE", "1979-01-07"),
    ("THERESA", "SCHMIDT", "FEMALE", "1984-04-25"),
    ("ADAM", "HARRISON", "MALE", "1971-07-13"),
    ("JULIA", "SNYDER", "FEMALE", "1989-10-29"),
    ("NATHAN", "SIMPSON", "MALE", "1975-02-02"),
    ("GRACE", "DUNCAN", "FEMALE", "1992-05-19"),
    ("ZACHARY", "HENDERSON", "MALE", "1980-08-08"),
    ("VICTORIA", "GRAHAM", "FEMALE", "1987-11-24"),
    ("PETER", "CRUZ", "MALE", "1967-03-16"),
    ("MEGAN", "SHAW", "FEMALE", "1993-06-30"),
    ("ETHAN", "BLACK", "MALE", "1976-09-11"),
    ("HANNAH", "PIERCE", "FEMALE", "1981-12-28"),
    ("CARL", "OLSON", "MALE", "1969-04-14"),
    ("ANDREA", "WARREN", "FEMALE", "1985-07-22"),
    ("KEITH", "AUSTIN", "MALE", "1972-10-05"),
    ("SARA", "STONE", "FEMALE", "1988-01-18"),
    ("ROGER", "HART", "MALE", "1964-05-31"),
    ("KATHRYN", "MILLS", "FEMALE", "1990-08-14"),
    ("WAYNE", "WAGNER", "MALE", "1978-11-27"),
    ("LILLIAN", "FORD", "FEMALE", "1983-02-09"),
    ("CHRISTIAN", "WELLS", "MALE", "1970-06-23"),
    ("ANNA", "WEBB", "FEMALE", "1986-09-06"),
    ("RUSSELL", "SIMPSON", "MALE", "1973-12-20"),
    ("EVELYN", "STEVENS", "FEMALE", "1979-03-15"),
    ("BOBBY", "TUCKER", "MALE", "1965-07-28"),
    ("DENISE", "PORTER", "FEMALE", "1991-10-11"),
    ("JOHNNY", "HUNTER", "MALE", "1977-01-04"),
    ("TAMMY", "HICKS", "FEMALE", "1984-04-17"),
    ("MARTIN", "CRAWFORD", "MALE", "1968-08-30"),
    ("IRENE", "BOYD", "FEMALE", "1992-11-23"),
    ("EUGENE", "MASON", "MALE", "1974-02-06"),
    ("JOAN", "MORENO", "FEMALE", "1980-05-19"),
]

# Routes by regime
ROUTES = {
    "APPR_DOMESTIC": [
        ("YYZ", "YVR", "CA", "CAD"),  # Toronto -> Vancouver
        ("YUL", "YYZ", "CA", "CAD"),  # Montreal -> Toronto
        ("YVR", "YUL", "CA", "CAD"),  # Vancouver -> Montreal
        ("YYC", "YOW", "CA", "CAD"),  # Calgary -> Ottawa
        ("YEG", "YHZ", "CA", "CAD"),  # Edmonton -> Halifax
    ],
    "APPR_INTL": [
        ("YYZ", "LAX", "US", "USD"),  # Toronto -> Los Angeles
        ("YUL", "MIA", "US", "USD"),  # Montreal -> Miami
        ("YVR", "SFO", "US", "USD"),  # Vancouver -> San Francisco
    ],
    "EU261_UK": [
        ("LHR", "YYZ", "GB", "GBP"),  # London -> Toronto
        ("LGW", "YUL", "GB", "GBP"),  # Gatwick -> Montreal
        ("MAN", "YVR", "GB", "GBP"),  # Manchester -> Vancouver
    ],
    "EU261_EUR": [
        ("CDG", "YUL", "FR", "EUR"),  # Paris -> Montreal
        ("FRA", "YYZ", "DE", "EUR"),  # Frankfurt -> Toronto
        ("AMS", "YVR", "NL", "EUR"),  # Amsterdam -> Vancouver
        ("FCO", "YYZ", "IT", "EUR"),  # Rome -> Toronto
        ("MAD", "YUL", "ES", "EUR"),  # Madrid -> Montreal
    ],
    "EU261_DOM_TOM": [
        ("PTP", "YUL", "GP", "EUR"),  # Guadeloupe -> Montreal
    ],
    "ASL": [
        ("TLV", "YYZ", "IL", "ILS"),  # Tel Aviv -> Toronto
    ],
    "OAL": [
        ("YYZ", "JFK", "US", "USD"),  # AC codeshare on UA
    ],
}

def get_passenger(idx):
    """Get passenger data by index."""
    p = PASSENGERS[idx % len(PASSENGERS)]
    return {
        "first_name": p[0],
        "last_name": p[1],
        "gender": p[2],
        "dob": p[3],
    }

def create_scenario(sit_id, title, description, route_type, route_idx, passengers,
                    special_flags=None, segment_status="HK", pax_type="ADT",
                    tags=None, booking_type="REVENUE"):
    """Create a PNR scenario JSON."""

    # Get route
    routes = ROUTES.get(route_type, ROUTES["APPR_DOMESTIC"])
    route = routes[route_idx % len(routes)]
    origin, dest, country, currency = route

    # Generate PNR code from SIT ID (e.g., FD-SIT-001 -> ZFD001)
    sit_num = sit_id.replace("FD-SIT-", "")
    pnr_code = f"ZFD{sit_num}"

    # Build passengers list
    pax_list = []
    for i, pax_idx in enumerate(passengers):
        p = get_passenger(pax_idx)
        pax = {
            "type": pax_type,
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "gender": p["gender"],
            "date_of_birth": p["dob"],
            "email": "chathuranga.viraj.qa@gmail.com",
            "phone": f"+1416555{1000 + pax_idx:04d}",
        }
        if special_flags and "aeroplan" in special_flags:
            pax["aeroplan"] = f"7{pax_idx:08d}"
        pax_list.append(pax)

    # Build segment
    segment = {
        "carrier": "AC",
        "operating_carrier": "AC" if route_type != "OAL" else "UA",
        "flight_number": f"{100 + int(sit_num):03d}",
        "operating_flight_number": f"{100 + int(sit_num):03d}",
        "origin": origin,
        "destination": dest,
        "dep_local": f"{BASE_DATE}T10:00:00",
        "arr_local": f"{BASE_DATE}T14:00:00",
        "dep_utc": f"{BASE_DATE}T14:00:00Z",
        "arr_utc": f"{BASE_DATE}T18:00:00Z",
        "booking_datetime": f"{BOOKING_DATE}T10:00:00Z",
        "aircraft": "77W" if route_type in ["EU261_UK", "EU261_EUR", "ASL"] else "320",
        "cabin": "Y",
        "status": segment_status,
        "arrival_terminal": "1",
    }

    # Special segment modifications
    if special_flags:
        if "cancelled" in special_flags:
            segment["status"] = "UN"
        if "oal" in special_flags:
            segment["operating_carrier"] = "UA"

    # Build ticketing
    ticket_base = f"014240{int(sit_num):06d}"
    ticketing = {
        "issuance_local_date": BOOKING_DATE,
        "fare": {"amount": "500.00", "currency": currency},
        "ticket_numbers": [f"{ticket_base}{i+1}" for i in range(len(pax_list))],
    }

    # Determine regime
    regime = "APPR"
    if route_type.startswith("EU261"):
        regime = "EU/UK 261"
    elif route_type == "ASL":
        regime = "ASL"
    elif route_type == "OAL":
        regime = "OAL"

    # Build tags
    all_tags = ["synthetic", "fd-sit", sit_id, regime.lower().replace("/", "-").replace(" ", "-"), "int-env"]
    if tags:
        all_tags.extend(tags)

    scenario = {
        "$schema_version": 2,
        "scenario_id": f"{pnr_code}-{BASE_DATE}",
        "title": f"{sit_id}: {title}",
        "description": description,
        "canvas": "_canvas/pnr_creation_domestic_ac.json",
        "contains_pii": False,
        "identity": {
            "pnr": pnr_code,
            "booking_date": BASE_DATE,
            "type": "PNR",
        },
        "point_of_sale": {
            "office_id": f"{origin}AC08AA",
            "iata_number": "01424012",
            "system_code": "1A",
            "agent_type": "AIRLINE",
            "agent_numeric_sign": "0001",
            "agent_initials": "FD",
            "duty_code": "SU",
            "agent_country": country,
            "agent_city": origin,
        },
        "last_modification_comment": f"SIM-{sit_id}-INT",
        "creation_comment": f"SIM-{sit_id}-INT",
        "passengers": pax_list,
        "segments": [segment],
        "ticketing": ticketing,
        "timeline": [
            {"version": 0, "at": f"{BOOKING_DATE}T10:00:00Z", "action": "bootstrap", "description": "Pre-ticketing stub"},
            {"version": 1, "at": f"{BOOKING_DATE}T10:00:01Z", "action": "ticketing_added", "description": "Ticketing reference attached"},
        ],
        "expected_cascade": {
            "db_end_state": {
                "trip": {"rows": 1, "status": "ACTIVE", "pnr": pnr_code, "pnr_id": f"{pnr_code}-{BASE_DATE}"},
                "passenger": {"rows": len(pax_list)},
                "flight_segment": {"rows": 1},
            },
            "total_cascade_budget_ms": 30000,
        },
        "classification": {"primary_code": "FD-SIT", "primary_name": "Flight Disruption SIT INT", "confidence": "high"},
        "tags": all_tags,
    }

    # Add special flags
    if special_flags:
        scenario["special_flags"] = special_flags
        if "employee" in special_flags:
            scenario["passengers"][0]["employee_id"] = "AC123456"
        if "infant" in special_flags:
            scenario["passengers"].append({
                "type": "INF",
                "first_name": "BABY",
                "last_name": pax_list[0]["last_name"],
                "gender": "MALE",
                "date_of_birth": "2025-06-01",
                "email": "chathuranga.viraj.qa@gmail.com",
                "phone": pax_list[0]["phone"],
            })
        if "youth" in special_flags:
            scenario["passengers"][0]["date_of_birth"] = "2012-06-15"  # ~14 years old
            scenario["passengers"][0]["type"] = "CHD"
        if "umnr" in special_flags:
            scenario["passengers"][0]["date_of_birth"] = "2016-06-15"  # ~10 years old
            scenario["passengers"][0]["type"] = "CHD"
            scenario["passengers"][0]["ssr"] = ["UMNR"]
        if "group" in special_flags:
            scenario["booking_type"] = "GROUP"
        if "redemption" in special_flags:
            scenario["booking_type"] = "REDEMPTION"

    return scenario

# Define all 132 test cases
TEST_CASES = [
    # Eligible - Travel Completed (FD-SIT-001 to FD-SIT-016)
    ("FD-SIT-001", "APPR 3-6hr delay CAD 400", "APPR eligible - 3 to <6 hour delay - CAD 400 cash", "APPR_DOMESTIC", 0, [0], None, ["appr", "tier1"]),
    ("FD-SIT-002", "APPR 3-6hr AC Wallet", "APPR eligible - 3 to <6 hour delay - AC Wallet +20% (CAD 480)", "APPR_DOMESTIC", 1, [1], ["aeroplan"], ["appr", "wallet"]),
    ("FD-SIT-003", "APPR 6-9hr delay CAD 700", "APPR eligible - 6 to <9 hour delay - CAD 700 cash", "APPR_DOMESTIC", 2, [2], None, ["appr", "tier2"]),
    ("FD-SIT-004", "APPR 6-9hr AC Wallet", "APPR eligible - 6 to <9 hour delay - AC Wallet (CAD 840)", "APPR_DOMESTIC", 3, [3], ["aeroplan"], ["appr", "wallet"]),
    ("FD-SIT-005", "APPR 9hr+ delay CAD 1000", "APPR eligible - 9 hour or greater delay - CAD 1,000 cash", "APPR_DOMESTIC", 4, [4], None, ["appr", "tier3"]),
    ("FD-SIT-006", "APPR 9hr+ AC Wallet", "APPR eligible - 9 hour or greater delay - AC Wallet (CAD 1,200)", "APPR_DOMESTIC", 0, [5], ["aeroplan"], ["appr", "wallet"]),
    ("FD-SIT-007", "APPR VOL/INVOL promise", "APPR eligible - VOL/INVOL promise calculation governs delay", "APPR_DOMESTIC", 1, [6], None, ["appr", "promise"]),
    ("FD-SIT-008", "EU/UK 261 UK 3-4hr GBP 260", "EU/UK 261 eligible - UK origin 3 to <4 hour delay - GBP 260", "EU261_UK", 0, [7], None, ["eu261", "uk"]),
    ("FD-SIT-009", "EU/UK 261 UK 4hr+ GBP 520", "EU/UK 261 eligible - UK origin 4 hour or greater delay - GBP 520", "EU261_UK", 1, [8], None, ["eu261", "uk"]),
    ("FD-SIT-010", "EU 261 EUR 3-4hr EUR 300", "EU 261 eligible - rest-of-Europe 3 to <4 hour delay - EUR 300", "EU261_EUR", 0, [9], None, ["eu261", "eur"]),
    ("FD-SIT-011", "EU 261 EUR 4hr+ EUR 600", "EU 261 eligible - rest-of-Europe 4 hour or greater delay - EUR 600", "EU261_EUR", 1, [10], None, ["eu261", "eur"]),
    ("FD-SIT-012", "EU 261 short/medium haul", "EU 261 eligible - short/medium-haul distance band - EUR 250 / EUR 400", "EU261_EUR", 2, [11], None, ["eu261", "short-haul"]),
    ("FD-SIT-013", "EU 261 DOM-TOM Guadeloupe", "EU 261 eligible - Guadeloupe (DOM-TOM) - EUR 400 flat", "EU261_DOM_TOM", 0, [12], None, ["eu261", "dom-tom"]),
    ("FD-SIT-014", "ASL Israel 480min+", "ASL eligible - 480 minute delay or greater - ILS 3,580", "ASL", 0, [13], None, ["asl", "israel"]),
    ("FD-SIT-015", "APPR multi-pax aggregated", "APPR eligible - multiple passengers - single case, aggregated payout", "APPR_DOMESTIC", 2, [14, 15, 16], None, ["appr", "multipax"]),
    ("FD-SIT-016", "APPR group individual claim", "APPR eligible - group booking - individual claim only", "APPR_DOMESTIC", 3, [17], ["group"], ["appr", "group"]),

    # Eligible - No Travel (FD-SIT-017 to FD-SIT-019)
    ("FD-SIT-017", "APPR no-travel controllable", "APPR no-travel controllable - compensation", "APPR_DOMESTIC", 4, [18], ["cancelled"], ["appr", "no-travel"]),
    ("FD-SIT-018", "EU/UK no-travel controllable", "EU/UK 261 no-travel controllable - compensation", "EU261_UK", 2, [19], ["cancelled"], ["eu261", "no-travel"]),
    ("FD-SIT-019", "ASL no-travel controllable", "ASL no-travel controllable - compensation", "ASL", 0, [20], ["cancelled"], ["asl", "no-travel"]),

    # Mixed Regime (FD-SIT-020 to FD-SIT-023)
    ("FD-SIT-020", "Mixed APPR+EU most generous", "APPR and EU/UK 261 both apply - most generous offer displayed", "EU261_UK", 0, [21], None, ["mixed", "appr", "eu261"]),
    ("FD-SIT-021", "Mixed FX conversion", "Most generous selection uses Bank of Canada FX conversion", "EU261_EUR", 3, [22], None, ["mixed", "fx"]),
    ("FD-SIT-022", "Mixed APPR+ASL", "APPR and ASL both apply - most generous offer displayed", "ASL", 0, [23], None, ["mixed", "appr", "asl"]),
    ("FD-SIT-023", "Mixed regime expired fallback", "Most generous regime expired - eligible fallback regime displayed", "EU261_UK", 1, [24], None, ["mixed", "expired"]),

    # Not Eligible (FD-SIT-024 to FD-SIT-036)
    ("FD-SIT-024", "Not eligible below threshold accept", "Not eligible - delay below threshold - customer accepts", "APPR_DOMESTIC", 0, [25], None, ["not-eligible", "below-threshold"]),
    ("FD-SIT-025", "Not eligible below threshold dispute", "Not eligible - delay below threshold - customer disputes", "APPR_DOMESTIC", 1, [26], None, ["not-eligible", "dispute"]),
    ("FD-SIT-026", "Not eligible uncontrollable", "Not eligible - uncontrollable / extraordinary disruption", "APPR_DOMESTIC", 2, [27], None, ["not-eligible", "uncontrollable"]),
    ("FD-SIT-028", "Not eligible employee", "Not eligible - employee or non-revenue passenger", "APPR_DOMESTIC", 3, [28], ["employee"], ["not-eligible", "employee"]),
    ("FD-SIT-029", "Not eligible infant", "Not eligible - infant without seat - adult eligible", "APPR_DOMESTIC", 4, [29], ["infant"], ["not-eligible", "infant"]),
    ("FD-SIT-030", "Not eligible 15+ days before", "Not eligible - change 15+ days before departure", "APPR_DOMESTIC", 0, [30], None, ["not-eligible", "advance-change"]),
    ("FD-SIT-031", "Not eligible denied boarding", "Not eligible - denied boarding", "APPR_DOMESTIC", 1, [31], None, ["not-eligible", "denied-boarding"]),
    ("FD-SIT-032", "Not eligible limitation period", "Not eligible - outside limitation period", "APPR_DOMESTIC", 2, [32], None, ["not-eligible", "expired"]),
    ("FD-SIT-033", "Not eligible all-OAL", "Not eligible - all-OAL itinerary - redirect to operating carrier", "OAL", 0, [33], ["oal"], ["not-eligible", "oal"]),
    ("FD-SIT-035", "Not eligible flight operated", "Not eligible - flight operated / no cancellation", "APPR_DOMESTIC", 3, [34], None, ["not-eligible", "operated"]),
    ("FD-SIT-036", "Not eligible MSL below threshold", "Not eligible - arrival delay below threshold despite MSL delay", "APPR_DOMESTIC", 4, [35], None, ["not-eligible", "msl"]),

    # No Determination & Pending (FD-SIT-037 to FD-SIT-044)
    ("FD-SIT-037", "No determination OAL redirect", "No determination - disruption on OAL - redirect", "OAL", 0, [36], ["oal"], ["no-determination", "oal"]),
    ("FD-SIT-038", "No determination Star Alliance", "No determination - disruption on Star Alliance partner - StarQuest", "OAL", 0, [37], ["oal"], ["no-determination", "starquest"]),
    ("FD-SIT-039", "No determination new destination", "No determination - unexpected new destination (new contract)", "APPR_DOMESTIC", 0, [38], None, ["no-determination", "new-dest"]),
    ("FD-SIT-040", "No determination 14-day polling", "No determination - no disruption code after 14-day polling", "APPR_DOMESTIC", 1, [39], None, ["no-determination", "polling"]),
    ("FD-SIT-041", "No determination MSL/OAL missing", "No determination - MSL or OAL data missing after 14-day polling", "APPR_DOMESTIC", 2, [40], None, ["no-determination", "missing-data"]),
    ("FD-SIT-042", "Pending 72hr wait window", "Pending - 72 hour wait window not elapsed - queue then welcome back", "APPR_DOMESTIC", 3, [41], None, ["pending", "wait-window"]),
    ("FD-SIT-043", "Welcome back eligible", "Welcome Back - eligible result after queue", "APPR_DOMESTIC", 4, [42], None, ["pending", "welcome-back", "eligible"]),
    ("FD-SIT-044", "Welcome back not eligible", "Welcome Back - not eligible result after queue", "APPR_DOMESTIC", 0, [43], None, ["pending", "welcome-back", "not-eligible"]),

    # Identification & Authentication (FD-SIT-045 to FD-SIT-053)
    ("FD-SIT-045", "ID exchanged tickets", "Identification by name and e-ticket with exchanged tickets", "APPR_DOMESTIC", 1, [44], None, ["identification", "exchanged"]),
    ("FD-SIT-046", "Aeroplan bypasses OTP", "Aeroplan authenticated session bypasses OTP", "APPR_DOMESTIC", 2, [45], ["aeroplan"], ["identification", "aeroplan"]),
    ("FD-SIT-047", "Aeroplan e-ticket xref", "Aeroplan plus e-ticket cross-reference resolves PNR", "APPR_DOMESTIC", 3, [46], ["aeroplan"], ["identification", "xref"]),
    ("FD-SIT-048", "No ID match shell case", "No identification match - shell case and manual review", "APPR_DOMESTIC", 4, [47], None, ["identification", "no-match", "manual"]),
    ("FD-SIT-049", "OTP fail IDV fallback", "OTP fails five times - IDV fallback succeeds", "APPR_DOMESTIC", 0, [48], None, ["identification", "otp-fail", "idv"]),
    ("FD-SIT-050", "OTP and IDV fail", "OTP fails and IDV fallback also fails - controlled end flow", "APPR_DOMESTIC", 1, [49], None, ["identification", "otp-fail", "idv-fail"]),
    ("FD-SIT-051", "OTP service unavailable", "OTP service unavailable - no shell case created", "APPR_DOMESTIC", 2, [50], None, ["identification", "otp-unavailable"]),
    ("FD-SIT-052", "Payment IDV fail fraud", "Payment-stage IDV fails - compensation held and fraud flagged", "APPR_DOMESTIC", 3, [51], None, ["identification", "payment-idv", "fraud"]),
    ("FD-SIT-053", "Travel agency OTP NOA", "Travel-agency email OTP with NOA upload - manual handling", "APPR_DOMESTIC", 4, [52], None, ["identification", "agency", "noa"]),

    # Intent & Conversation (FD-SIT-054 to FD-SIT-056)
    ("FD-SIT-054", "Ambiguous intent disambiguation", "Ambiguous intent - disambiguation routes to Flight Disruption", "APPR_DOMESTIC", 0, [53], None, ["intent", "disambiguation"]),
    ("FD-SIT-055", "FAQ then claim switch", "FAQ then claim - intent switch with no context loss", "APPR_DOMESTIC", 1, [54], None, ["intent", "faq", "switch"]),
    ("FD-SIT-056", "Multiple intents priority", "Multiple intents - Flight Disruption prioritised and processed sequentially", "APPR_DOMESTIC", 2, [55], None, ["intent", "multiple"]),

    # Payment & Country (FD-SIT-057 to FD-SIT-069)
    ("FD-SIT-057", "Interac cash payout", "Interac cash payout accepted", "APPR_DOMESTIC", 3, [56], None, ["payment", "interac"]),
    ("FD-SIT-058", "IBM BSM HSBC payout", "IBM / BSM / HSBC payout accepted with summary notification", "APPR_INTL", 0, [57], None, ["payment", "ibm"]),
    ("FD-SIT-059", "EFT WL Paycycle payout", "EFT / WL Paycycle payout - country banking details accepted", "APPR_INTL", 1, [58], None, ["payment", "eft"]),
    ("FD-SIT-060", "Cheque payout", "Cheque payout accepted; missing mailing address routes to manual", "APPR_DOMESTIC", 4, [59], None, ["payment", "cheque"]),
    ("FD-SIT-061", "AC Wallet batch fallback", "AC Wallet batch queued; unavailable falls back to cash", "APPR_DOMESTIC", 0, [60], ["aeroplan"], ["payment", "wallet", "fallback"]),
    ("FD-SIT-063", "Promo code compensation", "Promo code compensation - inventory reservation handled", "APPR_DOMESTIC", 1, [61], None, ["payment", "promo"]),
    ("FD-SIT-064", "Country payment mapping", "Country to payment-method mapping (USA EFT/USD, ROW Wire/JPY, Canada Interac/CAD)", "APPR_INTL", 2, [62], None, ["payment", "country-mapping"]),
    ("FD-SIT-065", "AC Wallet frozen fallback", "AC Wallet selected but Aeroplan frozen - graceful cash fallback", "APPR_DOMESTIC", 2, [63], ["aeroplan"], ["payment", "wallet", "frozen"]),
    ("FD-SIT-066", "IBM retry then manual", "IBM payment fails transiently then retry succeeds; terminal failure routes to manual", "APPR_DOMESTIC", 3, [64], None, ["payment", "retry"]),
    ("FD-SIT-067", "Payment callback mismatch", "Payment result callback mismatch - no side effect", "APPR_DOMESTIC", 4, [65], None, ["payment", "callback"]),
    ("FD-SIT-068", "Unsupported payout country", "Unsupported payout country - manual handling", "APPR_INTL", 0, [66], None, ["payment", "unsupported-country"]),
    ("FD-SIT-069", "Country residence missing", "Country of residence missing at preauth then corrected", "APPR_DOMESTIC", 0, [67], None, ["payment", "missing-country"]),

    # Passenger & Booking (FD-SIT-070 to FD-SIT-072)
    ("FD-SIT-070", "Youth passenger manual", "Youth passenger - route to manual review", "APPR_DOMESTIC", 1, [68], ["youth"], ["passenger", "youth"]),
    ("FD-SIT-071", "UMNR passenger manual", "UMNR passenger - route to manual review", "APPR_DOMESTIC", 2, [69], ["umnr"], ["passenger", "umnr"]),
    ("FD-SIT-072", "Split PNR group treatment", "Split-from-group PNR retains group treatment", "APPR_DOMESTIC", 3, [70], ["group"], ["passenger", "split"]),

    # Fraud Screening (FD-SIT-074 to FD-SIT-078)
    ("FD-SIT-074", "CyberSource YELLOW", "CyberSource YELLOW - route to manual review queue", "APPR_DOMESTIC", 4, [71], None, ["fraud", "yellow"]),
    ("FD-SIT-075", "CyberSource RED no dispute", "CyberSource RED no dispute - neutral rejection email", "APPR_DOMESTIC", 0, [72], None, ["fraud", "red"]),
    ("FD-SIT-076", "CyberSource RED dispute", "CyberSource RED with dispute - manual handling", "APPR_DOMESTIC", 1, [73], None, ["fraud", "red", "dispute"]),
    ("FD-SIT-077", "CyberSource unavailable", "CyberSource unavailable - fail closed, no false approval", "APPR_DOMESTIC", 2, [74], None, ["fraud", "unavailable"]),
    ("FD-SIT-078", "RDS flag overrides GREEN", "RDS business-rule flag overrides CyberSource GREEN - manual review", "APPR_DOMESTIC", 3, [75], None, ["fraud", "rds-flag"]),

    # Duplicate Detection (FD-SIT-079 to FD-SIT-081)
    ("FD-SIT-079", "Duplicate at eligibility", "Prior duplicate found at eligibility - controlled end flow", "APPR_DOMESTIC", 4, [76], None, ["duplicate", "eligibility"]),
    ("FD-SIT-080", "Duplicate at preauth", "New duplicate found at preauth - controlled handling", "APPR_DOMESTIC", 0, [77], None, ["duplicate", "preauth"]),
    ("FD-SIT-081", "No duplicate overlap", "No duplicate overlap - eligible flow continues", "APPR_DOMESTIC", 1, [78], None, ["duplicate", "no-overlap"]),

    # Wait-Window & Resilience (FD-SIT-083 to FD-SIT-086)
    ("FD-SIT-083", "Resume token invalid", "Wait-window expired but resume token invalid - controlled end flow", "APPR_DOMESTIC", 2, [79], None, ["resilience", "token-invalid"]),
    ("FD-SIT-084", "Due-task case load fail", "Due-task fires but case cannot be loaded - manual or retry", "APPR_DOMESTIC", 3, [80], None, ["resilience", "due-task"]),
    ("FD-SIT-085", "Service downtime retry", "Service downtime before eligibility decision - case created for retry", "APPR_DOMESTIC", 4, [81], None, ["resilience", "downtime"]),
    ("FD-SIT-086", "Session expiration resume", "Session expiration - resume or restart", "APPR_DOMESTIC", 0, [82], None, ["resilience", "session"]),

    # Case Management & Integrity (FD-SIT-087 to FD-SIT-091)
    ("FD-SIT-087", "Case Management unavailable", "Case Management unavailable at create shell - return later", "APPR_DOMESTIC", 1, [83], None, ["case-mgmt", "unavailable"]),
    ("FD-SIT-090", "Finalize replay once", "Finalize replay - downstream processing queued exactly once", "APPR_DOMESTIC", 2, [84], None, ["case-mgmt", "replay"]),
    ("FD-SIT-091", "Eligibility malformed", "Eligibility Assessment returns malformed payload - manual review", "APPR_DOMESTIC", 3, [85], None, ["case-mgmt", "malformed"]),

    # Notification & Reporting (FD-SIT-092 to FD-SIT-093)
    ("FD-SIT-092", "Notification failure no dup", "Notification failure after submission - payment not duplicated", "APPR_DOMESTIC", 4, [86], None, ["notification", "failure"]),
    ("FD-SIT-093", "Foreign currency CAD log", "Foreign-currency compensation - CAD equivalent logged for reporting", "EU261_EUR", 4, [87], None, ["notification", "fx-logging"]),

    # Third-Party (FD-SIT-094 to FD-SIT-099)
    ("FD-SIT-094", "Claims company CA/US blocked", "Claims company from Canada or US cannot submit; dispute path", "APPR_DOMESTIC", 0, [88], None, ["third-party", "claims-company", "blocked"]),
    ("FD-SIT-095", "Claims company EU manual", "Claims company from BE/DK/FR/DE - manual handling", "EU261_EUR", 0, [89], None, ["third-party", "claims-company", "eu"]),
    ("FD-SIT-096", "Travel agency NOA", "Travel agency submission - NOA required, manual handling", "APPR_DOMESTIC", 1, [90], None, ["third-party", "agency"]),
    ("FD-SIT-097", "Guardian manual", "Parent, guardian, caregiver, or legal tutor - manual handling", "APPR_DOMESTIC", 2, [91], None, ["third-party", "guardian"]),
    ("FD-SIT-098", "Missing authority manual", "Missing authority or relationship evidence - manual handling", "APPR_DOMESTIC", 3, [92], None, ["third-party", "missing-auth"]),
    ("FD-SIT-099", "Existing case branch", "Existing passenger case under or over 30 days - branch handling", "APPR_DOMESTIC", 4, [93], None, ["third-party", "existing-case"]),

    # Channel & Accessibility (FD-SIT-100 to FD-SIT-104)
    ("FD-SIT-100", "WhatsApp rich fallback", "WhatsApp rich components fall back to text", "APPR_DOMESTIC", 0, [94], None, ["channel", "whatsapp"]),
    ("FD-SIT-101", "Mobile web responsive", "Mobile web - responsive rendering completes the flow", "APPR_DOMESTIC", 1, [95], None, ["channel", "mobile"]),
    ("FD-SIT-102", "Unsupported language", "Unsupported language - controlled support path", "APPR_DOMESTIC", 2, [96], None, ["channel", "unsupported-lang"]),
    ("FD-SIT-103", "Max chat duration", "Maximum chat duration reached before acceptance - controlled handling", "APPR_DOMESTIC", 3, [97], None, ["channel", "max-duration"]),
    ("FD-SIT-104", "Negative sentiment handoff", "Threatening or persistently-negative sentiment - live-agent handoff", "APPR_DOMESTIC", 4, [98], None, ["channel", "sentiment"]),

    # Claims Dashboard (FD-SIT-105 to FD-SIT-106)
    ("FD-SIT-105", "Dispute not eligible", "Customer disputes a not-eligible decision - linked dispute case", "APPR_DOMESTIC", 0, [99], None, ["dashboard", "dispute"]),
    ("FD-SIT-106", "Banking error retry", "Banking error after payout - customer returns and payment re-processed", "APPR_DOMESTIC", 1, [100], None, ["dashboard", "banking-error"]),

    # Agentic Display (FD-SIT-107 to FD-SIT-108)
    ("FD-SIT-107", "Multi-segment display", "Agentic display of a multi-segment itinerary", "APPR_DOMESTIC", 2, [101], None, ["display", "multi-segment"]),
    ("FD-SIT-108", "IROP changed itinerary", "Journey display when itinerary changed multiple times (IROP)", "APPR_DOMESTIC", 3, [102], None, ["display", "irop"]),

    # Journey Selection (FD-SIT-109 to FD-SIT-110)
    ("FD-SIT-109", "Multi-select both bounds", "Multi-select: claiming for both bounds via 'Both'", "APPR_DOMESTIC", 4, [103], None, ["journey", "both-bounds"]),
    ("FD-SIT-110", "Neither selection no-match", "'Neither' at Journey Selection routes to No-Match", "APPR_DOMESTIC", 0, [104], None, ["journey", "neither"]),

    # Segment Selection (FD-SIT-111)
    ("FD-SIT-111", "Segment correction", "Customer corrects the delayed flight at Segment Selection", "APPR_DOMESTIC", 1, [105], None, ["segment", "correction"]),

    # Duplicate / Fraud (FD-SIT-113)
    ("FD-SIT-113", "Duplicate by other disputed", "Duplicate claim submitted by someone else, disputed", "APPR_DOMESTIC", 2, [106], None, ["duplicate", "other-person"]),

    # Timeframe (FD-SIT-115 to FD-SIT-116)
    ("FD-SIT-115", "Claim within 72h queued", "Claim filed within 72h of arrival is queued", "APPR_DOMESTIC", 3, [107], None, ["timeframe", "72h"]),
    ("FD-SIT-116", "Claim after window", "Claim filed after the permissible window (e.g. > 1 year)", "APPR_DOMESTIC", 4, [108], None, ["timeframe", "expired"]),

    # Case Status (FD-SIT-117)
    ("FD-SIT-117", "Case status waiting", "Passenger still waiting for compensation - case status", "APPR_DOMESTIC", 0, [109], None, ["status", "waiting"]),

    # Language (FD-SIT-119)
    ("FD-SIT-119", "French language", "Customer interacts in a different language (French / other)", "APPR_DOMESTIC", 1, [110], None, ["language", "french"]),

    # Appeal (FD-SIT-121 to FD-SIT-123)
    ("FD-SIT-121", "Appeal closed case", "Customer appeals / disputes a closed case", "APPR_DOMESTIC", 2, [111], None, ["appeal", "closed-case"]),
    ("FD-SIT-122", "Intent change after eligibility", "Passenger changes intent mid-conversation after eligibility decision", "APPR_DOMESTIC", 3, [112], None, ["intent", "mid-change"]),
    ("FD-SIT-123", "Appeal after next intent", "Passenger appeals FD rejection after moving to next intent", "APPR_DOMESTIC", 4, [113], None, ["appeal", "next-intent"]),

    # Third Party (FD-SIT-124)
    ("FD-SIT-124", "Claims company no attachment", "Claims company submits but no attachment", "APPR_DOMESTIC", 0, [114], None, ["third-party", "no-attachment"]),

    # Language (FD-SIT-125)
    ("FD-SIT-125", "Language change mid-convo", "Customer changes language mid-conversation", "APPR_DOMESTIC", 1, [115], None, ["language", "mid-change"]),

    # Amount / Currency (FD-SIT-126)
    ("FD-SIT-126", "Dispute currency conversion", "Disputes currency conversion", "EU261_EUR", 1, [116], None, ["payment", "fx-dispute"]),

    # Duplicate / Proactive Case (FD-SIT-127)
    ("FD-SIT-127", "Proactive case duplicate", "Customer claims FD; proactive case (non-reg comp issued) found for same journey/pax", "APPR_DOMESTIC", 2, [117], None, ["duplicate", "proactive"]),

    # Identification (FD-SIT-128)
    ("FD-SIT-128", "Misspelled first name", "[GenUC-02] User misspells the first name during identification", "APPR_DOMESTIC", 3, [118], None, ["identification", "misspell"]),

    # Dispute (FD-SIT-129 to FD-SIT-131)
    ("FD-SIT-129", "Second dispute", "[REUSE][GenUC-15] Dispute flow - 2nd dispute", "APPR_DOMESTIC", 4, [119], None, ["dispute", "second"]),
    ("FD-SIT-130", "Dispute alt email", "[REUSE] Dispute - Manual Handling - user provides alternative email", "APPR_DOMESTIC", 0, [120], None, ["dispute", "alt-email"]),
    ("FD-SIT-131", "Dispute speak person", "[REUSE] Dispute - Request to speak with a person -> Manual Handling", "APPR_DOMESTIC", 1, [121], None, ["dispute", "speak-person"]),

    # Multi-Pax (FD-SIT-132 to FD-SIT-134)
    ("FD-SIT-132", "Multipax permission no", "GenUC-07: S2 - Multipax permission / No", "APPR_DOMESTIC", 2, [122, 123], None, ["multipax", "permission-no"]),
    ("FD-SIT-133", "Multipax no own claim", "GenUC-07: S4 - Do not proceed with own claim", "APPR_DOMESTIC", 3, [124, 125], None, ["multipax", "no-own-claim"]),
    ("FD-SIT-134", "Multipax duplicate permission", "GenUC-07: S5 - Multi-pax Permission on Duplicate Claim", "APPR_DOMESTIC", 4, [126, 127], None, ["multipax", "duplicate-permission"]),

    # Duplicate (FD-SIT-135 to FD-SIT-137)
    ("FD-SIT-135", "Remove self duplicate", "GenUC-12: S1 - Remove self from duplicate, open own", "APPR_DOMESTIC", 0, [128], None, ["duplicate", "remove-self"]),
    ("FD-SIT-136", "Continue triage", "GenUC-12: S3 - User continues with Triage", "APPR_DOMESTIC", 1, [129], None, ["duplicate", "triage"]),
    ("FD-SIT-137", "Duplicate by other", "GenUC-14: S1 - Duplicate claim, submitted (opened by someone else)", "APPR_DOMESTIC", 2, [130], None, ["duplicate", "other-submitted"]),

    # Miscellaneous (FD-SIT-138 to FD-SIT-144)
    ("FD-SIT-138", "Empathy triggered", "Empathy triggered scenarios", "APPR_DOMESTIC", 3, [131], None, ["empathy"]),
    ("FD-SIT-139", "Case status action needed", "Case Status while a manual case is pending / needs customer input", "APPR_DOMESTIC", 4, [132], None, ["status", "action-needed"]),
    ("FD-SIT-140", "Crude language", "Customer uses crude language", "APPR_DOMESTIC", 0, [0], None, ["sentiment", "crude"]),
    ("FD-SIT-141", "Legal action threat", "Customer claims legal action", "APPR_DOMESTIC", 1, [1], None, ["sentiment", "legal"]),
    ("FD-SIT-142", "Wrong Aeroplan ACW", "Customer is not associated to the Aeroplan account on the booking but wants ACW compensation", "APPR_DOMESTIC", 2, [2], ["aeroplan"], ["payment", "wrong-aeroplan"]),
    ("FD-SIT-144", "Compensation outages", "Compensation processing outages", "APPR_DOMESTIC", 3, [3], None, ["resilience", "outage"]),
]

def main():
    """Generate all scenario files."""
    print(f"Generating {len(TEST_CASES)} FD SIT scenarios...")
    print(f"Output directory: {SCENARIOS_DIR}")
    print()

    generated = []
    for tc in TEST_CASES:
        sit_id, title, desc, route_type, route_idx, passengers, flags, tags = tc

        scenario = create_scenario(
            sit_id=sit_id,
            title=title,
            description=desc,
            route_type=route_type,
            route_idx=route_idx,
            passengers=passengers,
            special_flags=flags,
            tags=tags,
        )

        # Write to file
        pnr_code = scenario["identity"]["pnr"]
        filename = f"{pnr_code}-{BASE_DATE}.json"
        filepath = os.path.join(SCENARIOS_DIR, filename)

        with open(filepath, "w") as f:
            json.dump(scenario, f, indent=2)

        generated.append((sit_id, pnr_code, title))
        print(f"  {sit_id} -> {pnr_code}: {title[:50]}...")

    print()
    print(f"Generated {len(generated)} scenarios in {SCENARIOS_DIR}")

    # Create summary file
    summary_path = os.path.join(SCENARIOS_DIR, "_SUMMARY.md")
    with open(summary_path, "w") as f:
        f.write("# FD SIT PNR Scenarios Summary\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Total: {len(generated)} scenarios\n\n")
        f.write("| SIT ID | PNR Code | Title |\n")
        f.write("|--------|----------|-------|\n")
        for sit_id, pnr, title in generated:
            f.write(f"| {sit_id} | {pnr} | {title} |\n")

    print(f"Summary written to {summary_path}")

if __name__ == "__main__":
    main()
