"""Offline tests for seed/dds_pin.py rewrite logic (no boto3 / no live rule-engine)."""
from seed.dds_pin import rewrite_determination, s3_trace_key


def _template():
    return {
        "eventMetadata": {"trigger": "DISRUPTION_DETECTION_SERVICE", "timestamp": "2000-01-01T00:00:00.000Z"},
        "pnrIdentifier": {"pnrId": "ZZTMPL-2000-01-01", "pnr": "ZZTMPL"},
        "itineraryDetails": [{"mslFlight": {"segmentId": "ZZTMPL-2000-01-01-ST-1", "carrierCode": "AC",
                                            "flightNumber": "409", "departureAirport": "YUL",
                                            "arrivalAirport": "YYZ"}, "segments": []}],
        "compensationEligibility": [{
            "regime": "APPR", "boundRph": 0,
            "passengerEligibility": [{
                "passengerId": "ZZTMPL-2000-01-01-PT-2", "passengerType": "ADT",
                "mslFlight": {"segmentId": "ZZTMPL-2000-01-01-ST-1", "carrierCode": "AC",
                              "flightNumber": "409", "departureAirport": "YUL", "arrivalAirport": "YYZ"},
                "eligibilityStatus": "ELIGIBLE", "systemCode": "FD-APPR-EL-13",
                "compensationDetails": {"amount": 400, "currency": "CAD"}}]}],
    }


def test_rewrite_identity_and_flight():
    out = rewrite_determination(
        _template(), pnr_id="ZZFDAA-2026-06-13", locator="ZZFDAA", carrier="AC",
        flight_number=8002, origin="YYZ", destination="LHR", passenger_id="ZZFDAA-2026-06-13-PT-1",
        timestamp="2026-07-16T00:00:00.000Z")
    assert out["pnrIdentifier"] == {"pnrId": "ZZFDAA-2026-06-13", "pnr": "ZZFDAA"}
    pe = out["compensationEligibility"][0]["passengerEligibility"][0]
    # passenger collapsed to seeded PT-1
    assert pe["passengerId"] == "ZZFDAA-2026-06-13-PT-1"
    # flight rewritten to the seeded flight/route
    assert pe["mslFlight"] == {"segmentId": "ZZFDAA-2026-06-13-ST-1", "carrierCode": "AC",
                               "flightNumber": "8002", "departureAirport": "YYZ", "arrivalAirport": "LHR"}
    # verdict preserved
    assert pe["eligibilityStatus"] == "ELIGIBLE"
    assert pe["compensationDetails"] == {"amount": 400, "currency": "CAD"}
    assert out["eventMetadata"]["timestamp"] == "2026-07-16T00:00:00.000Z"
    # no template locator leakage
    assert "ZZTMPL" not in __import__("json").dumps(out)


def test_rewrite_does_not_mutate_input():
    t = _template()
    rewrite_determination(t, pnr_id="X-1", locator="X", carrier="AC", flight_number=1,
                          origin="A", destination="B")
    assert t["pnrIdentifier"]["pnr"] == "ZZTMPL"  # original untouched


def test_s3_trace_key_layout():
    k = s3_trace_key("traces/DDS", "2026-07-16", "abc-123")
    assert k == "traces/DDS/2026-07-16/abc-123/response.json"
