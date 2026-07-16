#!/usr/bin/env python3
"""Shared ASYNC OTP broker — ONE poller for the whole batch.

Instead of every session hammering the same Mailinator inbox on its own loop (which at high
concurrency rate-limits the API and drops codes), this daemon polls the inbox ONCE and appends every
parsed verification code to a shared JSONL feed. All concurrent sessions then read their code from that
feed via FeedOtpProvider (feed_otp.py) — no per-session Mailinator traffic, no inbox contention.

Feed line: {"mid","code","recv","subj","frm","body"} (body lowercased for per-session first-name match).
Dedup by Mailinator message id (seeded from any existing feed so restarts don't double-append).

Vendored from cct-qa-1/fd-int-flow/otp_broker.py; import fixed to package-relative and Mailinator
credentials read from the environment (QA_MAILINATOR_TOKEN / QA_MAILINATOR_DOMAIN / QA_MAILINATOR_INBOX)
instead of a hardcoded config_crt.json, so the module imports offline and the framework wires it from the
Env descriptor.

Usage (started/stopped by the batch runner or by hand):
  QA_MAILINATOR_TOKEN=... QA_MAILINATOR_DOMAIN=... QA_MAILINATOR_INBOX=... \
      python -m runner.engine.otp_broker <feed_path> [poll_seconds=4]
Stops on SIGTERM/Ctrl-C, or when a sentinel file "<feed_path>.stop" appears."""
import os
import sys
import json
import time
import re
import signal

from runner.engine.qa_framework.otp_provider import MailinatorOtpProvider

# code sits after "verification:" (spaces span the unescaped &nbsp;) OR standalone 6 digits that are NOT
# part of a CSS hex colour like #005078 (the (?<!#...) / (?!...) hex guards exclude it).
OTP_RX = re.compile(r"verification:\s*([0-9]{6})|(?<![#0-9A-Fa-f])([0-9]{6})(?![0-9A-Fa-f])")

_run = {"go": True}


def _extract(body):
    m = OTP_RX.search(body)
    return (m.group(1) or m.group(2)) if m else None


def main():
    feed = sys.argv[1] if len(sys.argv) > 1 else "otp_feed.jsonl"
    poll = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    stop_file = feed + ".stop"
    prov = MailinatorOtpProvider(
        token=os.environ["QA_MAILINATOR_TOKEN"],
        domain=os.environ["QA_MAILINATOR_DOMAIN"],
        inbox=os.environ["QA_MAILINATOR_INBOX"],
        subject_contains="", otp_regex=OTP_RX.pattern,
        timeout_seconds=1, poll_interval_seconds=1,
    )
    seen = set()
    if os.path.exists(feed):                       # seed dedup from prior lines
        for ln in open(feed, encoding="utf-8"):
            try:
                seen.add(json.loads(ln)["mid"])
            except Exception:
                pass

    def _stop(*_):
        _run["go"] = False
    try:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    except Exception:
        pass
    print(f"[otp-broker] polling {prov.inbox}@{prov.domain} every {poll}s -> {os.path.basename(feed)}", flush=True)
    added = 0
    while _run["go"] and not os.path.exists(stop_file):
        try:
            for m in (prov._get("").get("msgs") or []):
                mid = m.get("id")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                full = prov._get(f"/messages/{mid}")
                body = MailinatorOtpProvider._message_text(full)
                code = _extract(body)
                if not code:
                    continue
                rec = {"mid": mid, "code": code, "recv": prov._msg_epoch(m),
                       "subj": m.get("subject", ""), "frm": m.get("from", ""),
                       "body": " ".join(body.split()).lower()[:1500]}
                with open(feed, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
                added += 1
                print(f"[otp-broker] +code {code} recv={int(rec['recv'])} (total {added})", flush=True)
        except Exception as e:
            print(f"[otp-broker] poll error: {str(e)[:100]}", flush=True)
        time.sleep(poll)
    print(f"[otp-broker] stopped ({added} codes captured)", flush=True)


if __name__ == "__main__":
    main()
