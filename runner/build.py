"""Descriptor-driven glue: turn a RunContext + UseCase into a driven chatbot session and a canonical
Result. Pure code here (persona building, judge tool schema, Result assembly, config/OTP builders) imports
and unit-tests OFFLINE — the engine (boto3/websocket) is imported lazily inside run_case, and the judge's
Bedrock call is lazy inside its closure. Emit ONLY the canonical Result and validate every one."""
from __future__ import annotations

import datetime
import re
import uuid

from core.result import validate_result
from core.secrets import resolve_secret

# Default Amazon Connect init payload (web connector) — Env descriptors don't carry it, so the client
# needs a sensible default matching the CRT/INT web widget handshake.
_DEFAULT_INIT_PAYLOAD = {
    "ParticipantDetails": {"DisplayName": "Customer"},
    "attributes": {"platform": "connect:web", "locale": "en_CA", "preferredLanguage": "en",
                   "ipCountry": "CA-ON", "firstName": "TestUser"},
    "ChatDurationInMinutes": 60,
    "SupportedMessagingContentTypes": [
        "text/plain", "text/markdown", "application/json",
        "application/vnd.amazonaws.connect.message.interactive",
        "application/vnd.amazonaws.connect.message.interactive.response",
    ],
}


# ── persona ──────────────────────────────────────────────────────────────────
class _Blank(dict):
    """format_map helper: unknown {slots} render blank instead of raising KeyError."""
    def __missing__(self, key):
        return ""


def _split_name(passenger: str):
    parts = (passenger or "").strip().split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first, last


def build_persona(ctx, uc) -> str:
    """Feed-specific customer-sim system prompt with {first}{last}{pnr}{disruption} (+ seed extras) filled
    from the use-case seed. Uses the third_party branch when uc.third_party, else persona['default']."""
    persona = ctx.persona or {}
    branches = persona.get("branches") or {}
    if uc.third_party and branches.get("third_party"):
        tmpl = branches["third_party"]
    else:
        tmpl = persona.get("default", "")

    first, last = _split_name(uc.seed.passenger)
    extras = dict(uc.seed.extras or {})
    slots = {"first": first, "last": last, "pnr": uc.seed.pnr,
             "disruption": extras.get("disruption") or extras.get("Disruption") or ""}
    # make seed extras available as slots too (raw + normalized key), without overriding the core four
    for k, v in extras.items():
        slots.setdefault(k, v)
        slots.setdefault(k.strip().lower().replace(" ", "_"), v)
    try:
        return tmpl.format_map(_Blank(slots))
    except (ValueError, IndexError):
        # a stray unescaped brace in a persona template — fall back to leaving it untouched
        return tmpl


# ── judge ────────────────────────────────────────────────────────────────────
def build_judge(ctx):
    """Build a Bedrock submit_verdict tool whose decision enum == the feed's verdict_enum, plus a judge_fn
    that runs it against a transcript and returns a verdict dict. The Bedrock import is lazy (inside the
    closure) so this is offline-safe to construct + inspect."""
    enum = list((ctx.judge or {}).get("verdict_enum") or [])
    match_on = list((ctx.judge or {}).get("match_on") or [])
    tool = {"toolSpec": {
        "name": "submit_verdict",
        "description": "Judge the chatbot's FINAL outcome against the EXPECTED verdict for this case.",
        "inputSchema": {"json": {"type": "object", "properties": {
            "bot_outcome_summary": {"type": "string"},
            "decision": {"type": "string", "enum": enum} if enum else {"type": "string"},
            "amount": {"type": "string", "description": "Amount the bot quoted, e.g. 'CAD 400' or 'none'."},
            "reached_determination": {"type": "boolean"},
            "matches_expected": {"type": "boolean"},
            "checks": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "expected": {"type": "string"},
                "actual": {"type": "string"}, "pass": {"type": "boolean"}},
                "required": ["name", "expected", "actual", "pass"]}},
            "reasoning": {"type": "string"}},
            "required": ["bot_outcome_summary", "decision", "reached_determination",
                         "matches_expected", "checks", "reasoning"]}}}}

    def judge_fn(uc, transcript, br=None, model_id=None):
        from runner.engine import bedrock as B

        if br is None:
            br = B.bedrock_client()
        convo = "\n".join(f"{t.get('role', '').upper()}: {t.get('text', '')}"
                          for t in transcript if t.get("role") in ("customer", "assistant"))
        exp_amount = uc.seed.amount or {}
        amount_txt = f"{exp_amount.get('currency', '')} {exp_amount.get('value', '')}".strip() or "n/a"
        expected = (f"Test Case {uc.id} | PNR {uc.seed.pnr} | Passenger {uc.seed.passenger} | "
                    f"Regime {uc.regime} | EXPECTED decision {uc.verdict or uc.seed.status} | "
                    f"systemCode {uc.system_code} | Amount {amount_txt}")
        sysmsg = ("You are a strict QA evaluator for an airline chatbot. Compare the chatbot's FINAL "
                  f"outcome in the transcript against the EXPECTED verdict (match on: {', '.join(match_on) or 'decision'}). "
                  "The decision MUST be one of the allowed enum values. If the bot never renders an "
                  "outcome (loops, abstains, fails identity), set reached_determination=false and "
                  "matches_expected=false. Be precise; call submit_verdict.")
        user = f"EXPECTED:\n{expected}\n\nFULL CHAT TRANSCRIPT:\n{convo}\n\nEvaluate now."
        resp = B.converse(br, sysmsg, [{"role": "user", "content": [{"text": user}]}], tool,
                          model_id=model_id or B.DEFAULT_MODEL_ID)
        inp, _ = B.tool_input(resp, "submit_verdict")
        return inp or {"bot_outcome_summary": "judge returned no verdict", "decision": "UNKNOWN",
                       "amount": "none", "reached_determination": False, "matches_expected": False,
                       "checks": [], "reasoning": "no verdict returned"}

    return tool, judge_fn


# ── canonical-Result helpers ─────────────────────────────────────────────────
_SPLIT_RE = re.compile(r"[\s,;/|]+")
_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_CUR_RE = re.compile(r"\b([A-Z]{3})\b")


def _norm_amount(a):
    """Coerce a SeedSpec amount ({currency,value}) to the canonical amountOrNull (value must be a number)."""
    if not a:
        return None
    v = a.get("value")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return {"currency": a.get("currency", "") or "", "value": v}
    try:
        return {"currency": a.get("currency", "") or "", "value": float(str(v).replace(",", ""))}
    except (TypeError, ValueError):
        return None


def _parse_amount_text(txt):
    """Parse a judge-supplied amount string ('CAD 400', 'none') into amountOrNull."""
    if not txt:
        return None
    s = str(txt)
    if s.strip().lower() in ("none", "n/a", "na", "unknown", "", "0", "no"):
        return None
    num = _NUM_RE.search(s)
    if not num:
        return None
    try:
        value = float(num.group(0).replace(",", ""))
    except ValueError:
        return None
    cur_m = _CUR_RE.search(s)
    return {"currency": cur_m.group(1) if cur_m else "", "value": value}


def _flags(flags):
    if not flags:
        return []
    if isinstance(flags, (list, tuple)):
        return [str(x) for x in flags if str(x).strip()]
    return [t for t in _SPLIT_RE.split(str(flags).strip()) if t]


def _transcript(turns):
    out = []
    for t in turns or []:
        out.append({"role": t.get("role", ""), "text": t.get("text", ""),
                    "ts": t.get("ts"), "note": t.get("note")})
    return out


_TRANSIENT = ("connection", "websocket", "receive error", "timeout", "throttl", "temporarily")


def _error_bucket(error):
    if not error:
        return None
    e = error.lower()
    if "outage" in e or "temporarily" in e or "out of service" in e:
        return "outage"
    if "otp" in e or "verification" in e:
        return "otp"
    if any(k in e for k in _TRANSIENT):
        return "transient"
    if "did not call" in e or "bedrock" in e:
        return "driver"
    if "max_turns" in e:
        return "incomplete"
    return "other"


def _seed_block(ctx, uc, seed_source):
    """Verify the case's seed via seed.verify.verify_case when a source is available, else the offline
    stub (verified=false, checkpoints=[], dds=None). Never raises — a run works without the seed extra."""
    default = {"verified": False, "checkpoints": [], "dds": None}
    if seed_source is None:
        return default
    try:
        from seed.verify import verify_case

        areas = list((ctx.feed.checkpoints or {}).get("areas") or []) or None
        report = verify_case(uc, seed_source, areas=areas)
        checkpoints = [{"area": c.area, "pass": bool(c.ok)} for c in report.checks if c.ok is not None]
        return {"verified": bool(report.all_ok), "checkpoints": checkpoints, "dds": None}
    except Exception:
        return default


# ── run one case ─────────────────────────────────────────────────────────────
def _default_flow(uc, persona, first, chat_config, otp_provider, br):
    """Adapter: drive the real engine flow for one use-case. Imported lazily by run_case."""
    from runner.engine.flow import run_flow

    case = {"Test Case": uc.id, "PNR": uc.seed.pnr, "pnrId": uc.seed.pnr_id,
            "Passenger": uc.seed.passenger, "Regime": uc.regime}
    return run_flow(case, persona, first, chat_config, otp_provider, br=br)


def run_case(ctx, uc, chat_config, otp_provider, *, flow_fn=None, judge_fn=None, br=None,
             seed_source=None, run_id=None, run_date=None) -> dict:
    """Build persona, drive the flow, judge the transcript, and assemble a schema-valid canonical Result.

    flow_fn / judge_fn are injectable so the pure assembly path is unit-testable with NO network:
      flow_fn(uc, persona, first, chat_config, otp_provider, br) -> run dict
      judge_fn(uc, transcript, br) -> verdict dict
    """
    persona = build_persona(ctx, uc)
    first, _ = _split_name(uc.seed.passenger)

    flow = flow_fn or _default_flow
    run = flow(uc, persona, first, chat_config, otp_provider, br)

    transcript = run.get("transcript") or []
    jfn = judge_fn or build_judge(ctx)[1]
    if transcript:  # judge whenever the session produced a transcript (mirrors the CRT runner)
        try:
            verdict = jfn(uc, transcript, br)
        except Exception as ex:  # a judge failure must not lose the run
            verdict = {"bot_outcome_summary": f"judge error: {ex}", "decision": "UNKNOWN",
                       "amount": "none", "reached_determination": False, "matches_expected": False,
                       "checks": [], "reasoning": str(ex)}
    else:
        verdict = {"bot_outcome_summary": run.get("error") or "no transcript", "decision": "UNKNOWN",
                   "amount": "none", "reached_determination": False, "matches_expected": False,
                   "checks": [], "reasoning": run.get("error") or "no transcript produced"}

    run_date = run_date or datetime.date.today().isoformat()
    run_id = run_id or uuid.uuid4().hex[:12]

    checks = [{"name": c.get("name", ""), "expected": str(c.get("expected", "")),
               "actual": str(c.get("actual", "")), "pass": bool(c.get("pass"))}
              for c in (verdict.get("checks") or [])]

    result = {
        "schema_version": "1.0",
        "scenario_id": ctx.scenario_id(uc.id),
        "run": {"product": ctx.product.id, "env": ctx.env.id, "feed": ctx.feed.id,
                "date": run_date, "run_id": run_id,
                "started": run.get("started") or "", "duration_s": float(run.get("duration_s") or 0.0)},
        "case": {"test_case": uc.id, "pnr": uc.seed.pnr, "pnr_id": uc.seed.pnr_id,
                 "passenger": uc.seed.passenger, "regime": uc.regime,
                 "expected_status": uc.verdict or uc.seed.status or "",
                 "expected_system_code": uc.system_code or "",
                 "expected_amount": _norm_amount(uc.seed.amount),
                 "flags": _flags(uc.seed.flags), "third_party": bool(uc.third_party)},
        "seed": _seed_block(ctx, uc, seed_source),
        "auth": {"otp_fetched": bool(run.get("otp_fetched")), "contact_id": run.get("contact_id")},
        "verdict": {"decision": str(verdict.get("decision", "UNKNOWN")),
                    "amount": _parse_amount_text(verdict.get("amount")),
                    "reached_determination": bool(verdict.get("reached_determination", False)),
                    "matches_expected": bool(verdict.get("matches_expected", False)),
                    "checks": checks, "reasoning": str(verdict.get("reasoning", ""))},
        "harness": {"error": run.get("error"), "error_bucket": _error_bucket(run.get("error"))},
        "transcript": _transcript(transcript),
        "evidence": {"chat_html": None, "evidence_html": None},
    }
    validate_result(result)
    return result


# ── Env descriptor -> engine config / OTP provider ───────────────────────────
def chat_config_from_env(env):
    """Build a ChatbotConfig from the Env descriptor's chatbot block."""
    from runner.engine.qa_framework.config import ChatbotConfig

    cb = env.chatbot or {}
    return ChatbotConfig(
        base_url=cb.get("base_url", ""),
        api_key=cb.get("api_key", ""),
        endpoint_path=cb.get("endpoint_path", "/start-chat"),
        region=cb.get("region", "ca-central-1"),
        init_payload=cb.get("init_payload") or dict(_DEFAULT_INIT_PAYLOAD),
        timeout_seconds=int(cb.get("timeout_seconds", 30)),
        response_timeout_seconds=int(cb.get("response_timeout_seconds", 300)),
    )


class FixedOtpProvider:
    """Trivial provider for envs whose OTP strategy is 'fixed' (e.g. INT accepts any 6-digit code)."""
    def __init__(self, code: str = "123456"):
        self.code = code

    def wait_for_otp(self, since, *, otp_filter=None, timeout_seconds=None):
        return self.code


def otp_provider_from_env(env):
    """Build an OTP provider from the Env descriptor's otp block. strategy=mailinator ->
    MailinatorOtpProvider (token via resolve_secret(env.otp['token_secret'])); strategy=fixed ->
    FixedOtpProvider returning env.otp['code']."""
    otp = env.otp or {}
    strategy = otp.get("strategy", "fixed")
    if strategy == "mailinator":
        from runner.engine.qa_framework.otp_provider import MailinatorOtpProvider

        token = resolve_secret(otp["token_secret"])
        return MailinatorOtpProvider(
            token=token, domain=otp["domain"], inbox=otp["inbox"],
            subject_contains=otp.get("subject_contains", ""),
            otp_regex=otp.get("otp_regex") or r"([0-9]{6})",
            timeout_seconds=int(otp.get("timeout_seconds", 300)),
            poll_interval_seconds=float(otp.get("poll_interval_seconds", 6)),
        )
    return FixedOtpProvider(otp.get("code", "123456"))
