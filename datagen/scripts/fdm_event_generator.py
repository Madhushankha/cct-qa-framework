#!/usr/bin/env python3
"""
FDM Event Generator - Generate and publish FDM events via Kafka

Generates proper FDM events for flight_leg and flight_leg_updates:
1. FLIGHT_SCHEDULED - Creates flight_leg (parent row)
2. ARRIVAL_DELAY - Creates delay event
3. DEPARTURE_DELAY - Creates delay event
4. DELAY_CODE - Creates controllability code
5. LEG_STATUS - Creates arrival status

Usage:
    # Generate and publish FDM events for a flight
    python fdm_event_generator.py --flight AC301 --date 2026-06-15 --origin YUL --dest YYZ \
        --delay-minutes 240 --delay-code 41 --env int --live

    # Dry run (no publish)
    python fdm_event_generator.py --flight AC301 --date 2026-06-15 --origin YUL --dest YYZ \
        --delay-minutes 240 --env int
"""

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Environment configs
ENV_CONFIG = {
    "int": {
        "brokers": "b-1.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskintcac1.z22bz6.c3.kafka.ca-central-1.amazonaws.com:9092",
        "topic": "DERIVED-FDM-EVENTS-INT",
    },
    "crt": {
        "brokers": "b-1.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-2.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092,b-3.accctmskcrtcac1.05hf7o.c4.kafka.ca-central-1.amazonaws.com:9092",
        "topic": "DERIVED-FDM-EVENTS-CRT",
    },
}

# Delay code mappings (IATA codes)
DELAY_CODES = {
    "41": {"description": "AIRCRAFT_MAINTENANCE", "controllability": "CONTROLLABLE"},
    "42": {"description": "AIRCRAFT_CHANGE", "controllability": "CONTROLLABLE"},
    "61": {"description": "FLIGHT_CREW_SHORTAGE", "controllability": "CONTROLLABLE"},
    "64": {"description": "CREW_SCHEDULING", "controllability": "CONTROLLABLE"},
    "81": {"description": "ATC_RESTRICTIONS", "controllability": "UNCONTROLLABLE"},
    "82": {"description": "ATC_CAPACITY", "controllability": "UNCONTROLLABLE"},
    "83": {"description": "WEATHER", "controllability": "UNCONTROLLABLE"},
    "84": {"description": "DE_ICING", "controllability": "UNCONTROLLABLE"},
    "85": {"description": "AIRPORT_CLOSURE", "controllability": "UNCONTROLLABLE"},
    "86": {"description": "SECURITY", "controllability": "UNCONTROLLABLE"},
}


def generate_flight_leg_id(carrier: str, flight_number: int, origin: str, date: str) -> str:
    """Generate Aurora-format flight_leg_id (station-first)."""
    return f"{carrier}#{flight_number}#{origin}#{date}"


def generate_flink_flight_id(carrier: str, flight_number: int, date: str, origin: str) -> str:
    """Generate Flink-format flight_id (date-first)."""
    return f"{carrier}#{flight_number}#{date}#{origin}"


def generate_uuid() -> str:
    return str(uuid.uuid4())


def parse_time(date: str, time_str: str) -> str:
    """Convert date + time to ISO format."""
    return f"{date}T{time_str}:00Z"


class FDMEventGenerator:
    def __init__(self, carrier: str, flight_number: int, origin: str, destination: str,
                 date: str, scheduled_dep: str = "10:00", scheduled_arr: str = "14:00",
                 delay_minutes: int = 0, delay_code: str = "41"):
        self.carrier = carrier
        self.flight_number = flight_number
        self.origin = origin
        self.destination = destination
        self.date = date
        self.scheduled_dep = scheduled_dep
        self.scheduled_arr = scheduled_arr
        self.delay_minutes = delay_minutes
        self.delay_code = delay_code

        # Computed values
        self.flight_leg_id = generate_flight_leg_id(carrier, flight_number, origin, date)
        self.flink_flight_id = generate_flink_flight_id(carrier, flight_number, date, origin)
        self.scheduled_dep_iso = parse_time(date, scheduled_dep)
        self.scheduled_arr_iso = parse_time(date, scheduled_arr)

        # Calculate actual times with delay
        arr_dt = datetime.fromisoformat(self.scheduled_arr_iso.replace('Z', '+00:00'))
        actual_arr_dt = arr_dt + timedelta(minutes=delay_minutes)
        self.actual_arr_iso = actual_arr_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        dep_dt = datetime.fromisoformat(self.scheduled_dep_iso.replace('Z', '+00:00'))
        actual_dep_dt = dep_dt + timedelta(minutes=max(0, delay_minutes - 30))
        self.actual_dep_iso = actual_dep_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _base_event(self, event_name: str, event_type: str = "UPDATE") -> dict:
        """Create base event structure."""
        return {
            "eventName": event_name,
            "sourceFeed": "FDM",
            "eventType": event_type,
            "entityId": self.flink_flight_id,
            "id": generate_uuid(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "1.0.0",
            "isReplay": False,
            "data": {
                "flightId": self.flink_flight_id,
                "carrier": self.carrier,
                "flightNumber": self.flight_number,
                "departureAirport": self.origin,
                "arrivalAirport": self.destination,
                "scheduledDepartureTime": self.scheduled_dep_iso,
                "scheduledArrivalTime": self.scheduled_arr_iso,
                "legSequenceNumber": 1,
                "lastUpdate": datetime.utcnow().isoformat() + "Z",
            }
        }

    def generate_flight_scheduled(self) -> dict:
        """Generate FLIGHT_SCHEDULED event - creates flight_leg row."""
        event = self._base_event("FLIGHT_SCHEDULED", "CREATE")
        event["data"].update({
            "legState": "SKD",
            "serviceType": "J",
            "aircraftOwner": self.carrier,
            "aircraftSubtype": "320",
            "aircraftConfiguration": "Y180",
            "registration": f"C-F{self.carrier}{self.flight_number % 1000:03d}",
            "seatsF": 0,
            "seatsC": 16,
            "seatsY": 164,
            "createdAt": datetime.utcnow().isoformat() + "Z",
        })
        return event

    def generate_departure_delay(self) -> dict:
        """Generate DEPARTURE_DELAY event."""
        event = self._base_event("DEPARTURE_DELAY")
        event["data"].update({
            "legState": "ETD",
            "estimatedTimeDeparture": self.actual_dep_iso,
            "fdm_original_type": "ETD_UPDATE",
        })
        return event

    def generate_arrival_delay(self) -> dict:
        """Generate ARRIVAL_DELAY event."""
        event = self._base_event("ARRIVAL_DELAY")
        event["data"].update({
            "legState": "DEP",
            "estimatedTimeArrival": self.actual_arr_iso,
            "fdm_original_type": "ETA_UPDATE",
        })
        return event

    def generate_delay_code(self) -> dict:
        """Generate DELAY_CODE event with controllability."""
        event = self._base_event("DELAY_CODE")
        code_info = DELAY_CODES.get(self.delay_code, DELAY_CODES["41"])
        event["data"].update({
            "legState": "DEP",
            "delayCode": self.delay_code,
            "delayCodeDescription": code_info["description"],
            "controllability": code_info["controllability"],
            "delayMinutes": self.delay_minutes,
        })
        return event

    def generate_leg_status_arrived(self) -> dict:
        """Generate LEG_STATUS event for arrival."""
        event = self._base_event("FLIGHT_ARRIVED")
        event["data"].update({
            "legState": "ARR",
            "fdm_original_type": "ON_BLOCKS",
            "onBlocksTime": self.actual_arr_iso,
            "actualArrivalTime": self.actual_arr_iso,
        })
        return event

    def generate_all_events(self) -> list:
        """Generate all FDM events in proper order."""
        events = [
            self.generate_flight_scheduled(),
        ]

        if self.delay_minutes > 0:
            events.extend([
                self.generate_departure_delay(),
                self.generate_arrival_delay(),
                self.generate_delay_code(),
            ])

        events.append(self.generate_leg_status_arrived())

        return events


def write_ndjson(events: list, output_path: Path, topic: str):
    """Write events to NDJSON file with __meta wrapper."""
    with open(output_path, 'w') as f:
        for event in events:
            record = {
                "__meta": {
                    "topic": topic,
                    "ts_ms": int(datetime.utcnow().timestamp() * 1000),
                    "key": event["entityId"],
                },
                "payload": event,
            }
            f.write(json.dumps(record) + "\n")


def publish_via_kcat(brokers: str, topic: str, events: list, dry_run: bool = True):
    """Publish events to Kafka via kcat."""
    print(f"\n{'DRY RUN - ' if dry_run else ''}Publishing {len(events)} FDM events to {topic}")
    print("=" * 60)

    for i, event in enumerate(events):
        event_name = event["eventName"]
        entity_id = event["entityId"]
        payload = json.dumps(event, separators=(",", ":"))

        print(f"  [{i+1}/{len(events)}] {event_name}")
        print(f"         entityId: {entity_id}")
        print(f"         size: {len(payload)} bytes")

        if not dry_run:
            cmd = ["kcat", "-P", "-b", brokers, "-t", topic, "-K", "\t"]
            input_bytes = (entity_id + "\t" + payload + "\n").encode()
            try:
                subprocess.run(cmd, input=input_bytes, check=True, capture_output=True)
                print(f"         ✓ Published")
            except subprocess.CalledProcessError as e:
                print(f"         ✗ Failed: {e.stderr.decode() if e.stderr else e}")
                return False

    if dry_run:
        print("\nDRY RUN - No events published. Add --live to publish.")
    else:
        print(f"\n✓ Published {len(events)} FDM events to {topic}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Generate and publish FDM events")
    parser.add_argument("--flight", required=True, help="Flight number (e.g., AC301)")
    parser.add_argument("--date", required=True, help="Flight date (YYYY-MM-DD)")
    parser.add_argument("--origin", required=True, help="Origin airport (e.g., YUL)")
    parser.add_argument("--dest", required=True, help="Destination airport (e.g., YYZ)")
    parser.add_argument("--dep-time", default="10:00", help="Scheduled departure (HH:MM)")
    parser.add_argument("--arr-time", default="14:00", help="Scheduled arrival (HH:MM)")
    parser.add_argument("--delay-minutes", type=int, default=0, help="Arrival delay in minutes")
    parser.add_argument("--delay-code", default="41", help="IATA delay code (default: 41)")
    parser.add_argument("--env", default="int", choices=["int", "crt"], help="Environment")
    parser.add_argument("--live", action="store_true", help="Actually publish (default: dry run)")
    parser.add_argument("--output", help="Output NDJSON file path")

    args = parser.parse_args()

    # Parse flight number
    carrier = args.flight[:2].upper()
    flight_num = int(args.flight[2:])

    # Create generator
    gen = FDMEventGenerator(
        carrier=carrier,
        flight_number=flight_num,
        origin=args.origin.upper(),
        destination=args.dest.upper(),
        date=args.date,
        scheduled_dep=args.dep_time,
        scheduled_arr=args.arr_time,
        delay_minutes=args.delay_minutes,
        delay_code=args.delay_code,
    )

    # Generate events
    events = gen.generate_all_events()

    print("=" * 60)
    print("FDM Event Generator")
    print("=" * 60)
    print(f"Flight:        {carrier}{flight_num}")
    print(f"Route:         {args.origin} → {args.dest}")
    print(f"Date:          {args.date}")
    print(f"Scheduled:     {args.dep_time} → {args.arr_time}")
    print(f"Delay:         {args.delay_minutes} minutes")
    print(f"Delay Code:    {args.delay_code} ({DELAY_CODES.get(args.delay_code, {}).get('description', 'UNKNOWN')})")
    print(f"Controllability: {DELAY_CODES.get(args.delay_code, {}).get('controllability', 'UNKNOWN')}")
    print(f"flight_leg_id: {gen.flight_leg_id}")
    print(f"Environment:   {args.env.upper()}")
    print(f"Events:        {len(events)}")

    # Write to file if requested
    if args.output:
        output_path = Path(args.output)
        write_ndjson(events, output_path, ENV_CONFIG[args.env]["topic"])
        print(f"\nWritten to: {output_path}")

    # Publish
    config = ENV_CONFIG[args.env]
    success = publish_via_kcat(
        brokers=config["brokers"],
        topic=config["topic"],
        events=events,
        dry_run=not args.live,
    )

    if success and args.live:
        print("\n" + "=" * 60)
        print("FDM Events Published!")
        print("=" * 60)
        print(f"""
Wait ~30 seconds for processing, then verify:
  - flight_leg: {gen.flight_leg_id}
  - flight_leg_updates: {len(events) - 1} rows expected

The transformer will:
  1. Create flight_leg from FLIGHT_SCHEDULED
  2. Create flight_leg_updates from delay/status events
""")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
