"""FeedOtpProvider — drop-in replacement for MailinatorOtpProvider that reads codes from the shared
JSONL feed written by otp_broker.py instead of hitting Mailinator directly. Same wait_for_otp interface,
so the flow uses it transparently when a feed path is configured. No per-session Mailinator traffic ->
no inbox contention at high concurrency; the single broker is the only client polling the API.

Vendored from cct-qa-1/fd-int-flow/feed_otp.py; import fixed to package-relative."""
import os
import json
import time
from datetime import timezone, timedelta

from runner.engine.qa_framework.otp_provider import OtpError


class FeedOtpProvider:
    def __init__(self, feed_path, *, skew_buffer_seconds=30, timeout_seconds=300, poll_interval_seconds=3):
        self.feed_path = feed_path
        self.skew_buffer_seconds = skew_buffer_seconds
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def _read(self):
        if not os.path.exists(self.feed_path):
            return []
        out = []
        for ln in open(self.feed_path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out

    def wait_for_otp(self, since, *, otp_filter=None, timeout_seconds=None):
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        cutoff = (since - timedelta(seconds=self.skew_buffer_seconds)).timestamp()
        f = otp_filter
        body_contains = ((getattr(f, "body_contains", None) or "") if f else "").lower()
        subj_contains = ((getattr(f, "subject_contains", None) or "") if f else "").lower()
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            fresh = sorted((e for e in self._read() if float(e.get("recv", 0)) >= cutoff),
                           key=lambda e: e.get("recv", 0), reverse=True)
            for e in fresh:
                if subj_contains and subj_contains not in (e.get("subj", "") or "").lower():
                    continue
                if body_contains and body_contains not in (e.get("body", "") or ""):
                    continue
                if e.get("code"):
                    return e["code"]
            time.sleep(self.poll_interval_seconds)
        raise OtpError(f"No feed OTP matching body~{body_contains!r} within {timeout}s "
                       f"(feed {os.path.basename(self.feed_path)})")
