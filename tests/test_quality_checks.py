from quality.checks import deterministic_checks


def _msg(role, text, ts=None):
    return {"role": role, "text": text, "ts": ts, "note": None}


def test_duplicate_bot_message_flagged():
    transcript = [
        _msg("customer", "hi"),
        _msg("bot", "Hello! How can I help you today?"),
        _msg("customer", "what about my claim"),
        _msg("bot", "Hello! How can I help you today?"),
    ]
    findings = deterministic_checks(transcript)
    assert any(f["area"] == "1 Duplicate messages" and f["severity"] == "High" for f in findings)


def test_duplicate_consecutive_user_message_flagged():
    transcript = [
        _msg("customer", "my flight was delayed"),
        _msg("customer", "my flight was delayed"),
        _msg("bot", "I'm sorry to hear that."),
    ]
    findings = deterministic_checks(transcript)
    assert any(f["area"] == "1 Duplicate messages" and f["severity"] == "Medium" for f in findings)


def test_empty_bot_bubble_flagged():
    transcript = [_msg("customer", "hi"), _msg("bot", "")]
    findings = deterministic_checks(transcript)
    assert any(f["issue"] == "Empty bot message bubble" for f in findings)


def test_leaked_internal_code_flagged():
    transcript = [
        _msg("customer", "why was I denied"),
        _msg("bot", "Your claim system code is FD-APPR-EL-400, please hold."),
    ]
    findings = deterministic_checks(transcript)
    leaks = [f for f in findings if f["area"] == "9/10 Content & security"]
    assert leaks and leaks[0]["severity"] == "High"
    assert "FD-APPR" in leaks[0]["evidence"]


def test_leaked_execution_traces_flagged():
    transcript = [_msg("bot", "Checking execution_traces for your case now.")]
    findings = deterministic_checks(transcript)
    assert any(f["area"] == "9/10 Content & security" for f in findings)


def test_technical_error_shown_flagged():
    transcript = [_msg("bot", "Sorry, something went wrong. Please try again later.")]
    findings = deterministic_checks(transcript)
    assert any(f["area"] == "7 API/error handling" for f in findings)


def test_repeated_bot_question_flagged():
    transcript = [
        _msg("bot", "What is your booking reference?"),
        _msg("customer", "..."),
        _msg("bot", "What is your booking reference?"),
        _msg("customer", "..."),
        _msg("bot", "What is your booking reference?"),
    ]
    findings = deterministic_checks(transcript)
    assert any(f["area"] == "5 Conversation flow" for f in findings)


def test_clean_transcript_has_no_findings():
    transcript = [
        _msg("customer", "Hi, I'd like to check my flight delay compensation."),
        _msg("bot", "Sure, I can help with that. Could you share your booking reference?"),
        _msg("customer", "ABC123"),
        _msg("bot", "Thanks! You're eligible for compensation of $400 CAD."),
    ]
    findings = deterministic_checks(transcript)
    assert findings == []


def test_empty_transcript_returns_no_findings():
    assert deterministic_checks([]) == []


def test_finding_shape_has_required_keys():
    transcript = [_msg("bot", "Checking execution_traces for your case now.")]
    findings = deterministic_checks(transcript)
    assert findings
    f = findings[0]
    assert set(["layer", "area", "severity", "issue", "evidence"]) <= set(f.keys())
    assert f["layer"] == "deterministic"
