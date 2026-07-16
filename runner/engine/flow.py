"""The robust widget-aware + OTP-aware turn loop — extracted from cct-qa-1/fd-int-flow/run_nc_crt.py's
run_flow, adapted to take a ChatbotConfig + an OTP provider as PARAMETERS instead of reading module
globals. This is the loop that completed ~100% on CRT: it captures last_widget, presents options to the
customer-sim, calls send_widget_select, drains 'processing' placeholders, detects backend outages, and
handles the email-OTP SINGLE_SELECT (select EMAIL -> wait for the code -> submit it).

Imports of the engine client (which lazily needs boto3/websocket) happen inside run_flow so this module
imports offline; the Bedrock driver lives in runner.engine.bedrock (also lazy)."""
from __future__ import annotations

import datetime
import time
from datetime import timezone

from runner.engine import bedrock as B

# ── phrase heuristics (verbatim from the CRT runner) ─────────────────────────
OTP_ASK = ("enter the 6-digit", "enter the code", "enter the 6 digit", "received the code",
           "6-digit code here", "please enter the verification", "type the code")

PLACEHOLDER = ("processing your request and will assist", "air canada assistant", "how i can help")

# Booking-lookup outage: when the backend is unavailable the bot says these — terminate the session
# immediately instead of letting the driver keep retrying (no point moving the chat forward).
OUTAGE = ("lookup system is temporarily unavailable", "booking lookup system", "temporarily unavailable",
          "unable to look up your booking", "system is temporarily unavailable", "out of service",
          "lookup is still temporarily unavailable")


def is_otp_ask(t):
    t = (t or "").lower()
    return any(k in t for k in OTP_ASK)


def is_placeholder(t):
    t = (t or "").lower()
    return any(k in t for k in PLACEHOLDER)


def is_outage(t):
    return any(k in (t or "").lower() for k in OUTAGE)


def drain_placeholders(client, reply, tries=2):
    for _ in range(tries):
        if not is_placeholder(reply):
            return reply
        try:
            reply = client._collect_bot_reply()
        except Exception:
            return reply
    return reply


def now_iso():
    return datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_flow(case, sys_prompt, fn, chat_config, otp, *, br=None, model_id=B.DEFAULT_MODEL_ID,
             max_turns=22, on_otp_done=None):
    """Drive ONE chatbot session.

    case        opaque dict (carried through for the caller; not required by the loop)
    sys_prompt  the customer-simulator system prompt (feed persona, slot-filled)
    fn          the passenger FIRST name — scopes the OTP email body match (shared inbox)
    chat_config a runner.engine.qa_framework.config.ChatbotConfig (from the Env descriptor)
    otp         an OTP provider with wait_for_otp(since, otp_filter=..., timeout_seconds=...)
    br          an optional pre-built Bedrock client (else one is created)
    on_otp_done invoked ONCE when identity/OTP clears (or at session end) so the orchestrator can
                free an 'OTP-phase' slot and admit the next session while this one keeps going.

    Returns {transcript, contact_id, otp_fetched, error, started, duration_s, widgets}."""
    from runner.engine.capture_client import CapturingChatClient
    from runner.engine.qa_framework.amazon_connect_client import ChatbotError
    from runner.engine.qa_framework.otp_provider import OtpFilter

    _otp_released = [False]

    def _release_otp():
        if on_otp_done and not _otp_released[0]:
            _otp_released[0] = True
            try:
                on_otp_done()
            except Exception:
                pass

    client = CapturingChatClient(config=chat_config)
    if br is None:
        br = B.bedrock_client(region=chat_config.region)
    started = datetime.datetime.now(timezone.utc)
    transcript = []

    def rec(role, text, note=""):
        transcript.append({"role": role, "text": text, "ts": now_iso(), "note": note})

    _hw = [0]

    def _norm_ts(s):
        return (s.split(".")[0].rstrip("Z") + "Z") if s else now_iso()

    def flush_frames(note=""):
        frames = client.all_bot_frames[_hw[0]:]
        _hw[0] = len(client.all_bot_frames)
        for fr in frames:
            transcript.append({"role": "assistant", "text": fr["text"], "ts": _norm_ts(fr.get("ts")), "note": note})
        return frames

    print(f"[{now_iso()}] start_session ...", flush=True)
    client.start_session()
    greeting = (client._greeting_text or "").strip() or "(no greeting)"
    if not flush_frames(note="greeting") and greeting != "(no greeting)":
        rec("assistant", greeting, note="greeting")
    print(f"[session] ContactId={client.contact_id}", flush=True)

    messages = [{"role": "user", "content": [{"text": f"[Assistant greeting]\n{greeting}"}]}]
    last_reply = greeting
    otp_done = False
    await_otp = False
    error = None
    for i in range(max_turns):
        try:
            resp = B.converse(br, sys_prompt, messages, B.CUSTOMER_TOOL, model_id=model_id)
        except Exception as e:
            error = f"driver bedrock error: {e}"
            print(f"[turn {i+1}] {error}", flush=True)
            break
        inp, tuid = B.tool_input(resp, "customer_turn")
        if inp is None:
            error = "driver LLM did not call customer_turn"
            break
        cust_msg = (inp.get("message") or "").strip()
        done = bool(inp.get("conversation_complete"))
        note = inp.get("private_note", "")
        messages.append({"role": "assistant", "content": [{"toolUse": {"toolUseId": tuid, "name": "customer_turn", "input": inp}}]})
        pending = getattr(client, "last_widget", None)
        t0 = time.time()
        try:
            if await_otp and not otp_done:
                await_otp = False
                print(f"[turn {i+1}] email selected — waiting for OTP prompt ...", flush=True)
                for _ in range(3):
                    try:
                        p = client._collect_bot_reply()
                        last_reply = p
                        if is_otp_ask(p) or "sent" in p.lower() or "code" in p.lower():
                            break
                    except ChatbotError:
                        break
                flush_frames(note="otp-prompt")
                cust_msg = otp.wait_for_otp(since=started, otp_filter=OtpFilter(body_contains=fn))
                otp_done = True
                note = "otp"
                _release_otp()
                print(f"[turn {i+1}] OTP = {cust_msg}", flush=True)
                rec("customer", cust_msg, note=note)
                reply = client.ask(cust_msg)
            elif pending and not done:
                note = f"widget:{pending['wt']}->{cust_msg[:20]}"
                rec("customer", cust_msg, note=note)
                print(f"\n[turn {i+1}] CUSTOMER(widget {pending['wt']})> {cust_msg}", flush=True)
                reply = client.send_widget_select(cust_msg)
                if pending["wt"] == "SINGLE_SELECT" and "email" in reply.lower() and any(k in reply.lower() for k in ("processing", "sent", "got it")):
                    await_otp = True
            else:
                client.last_widget = None
                if is_otp_ask(last_reply) and not otp_done:
                    print(f"[turn {i+1}] OTP-ask — fetching code ({fn}) ...", flush=True)
                    cust_msg = otp.wait_for_otp(since=started, otp_filter=OtpFilter(body_contains=fn))
                    otp_done = True
                    note = "otp"
                    _release_otp()
                    print(f"[turn {i+1}] OTP = {cust_msg}", flush=True)
                rec("customer", cust_msg, note=note)
                print(f"\n[turn {i+1}] CUSTOMER> {cust_msg}   (done={done})", flush=True)
                reply = client.ask(cust_msg)
        except ChatbotError as e:
            flush_frames()
            reply = f"[ChatbotError] {e}"
            messages.append({"role": "user", "content": [{"toolResult": {"toolUseId": tuid, "content": [{"text": reply}]}}]})
            rec("assistant", reply, note="error")
            error = str(e)
            break
        except Exception as e:
            flush_frames()
            reply = f"[error] {e}"
            messages.append({"role": "user", "content": [{"toolResult": {"toolUseId": tuid, "content": [{"text": reply}]}}]})
            rec("assistant", reply, note="error")
            error = str(e)
            break
        reply = drain_placeholders(client, reply)
        last_reply = reply
        flush_frames()
        print(f"[turn {i+1}] ASSISTANT> {reply[:280]}   ({round(time.time()-t0,1)}s)", flush=True)
        messages.append({"role": "user", "content": [{"toolResult": {"toolUseId": tuid, "content": [{"text": reply}]}}]})
        if is_outage(reply):   # backend booking-lookup out of service — terminate, don't move on
            error = "booking-lookup outage — session terminated"
            print(f"[turn {i+1}] OUTAGE detected — terminating session", flush=True)
            break
        if done:
            break
    else:
        error = error or "reached max_turns"

    if client.connection_token:
        try:
            client._send_message("End chat")
            time.sleep(2)
        except Exception:
            pass
    try:
        client.close()
    except Exception:
        pass
    _release_otp()
    return {"transcript": transcript, "contact_id": client.contact_id, "otp_fetched": otp_done, "error": error,
            "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "widgets": getattr(client, "captured_widgets", []),
            "duration_s": round((datetime.datetime.now(timezone.utc) - started).total_seconds(), 1)}
