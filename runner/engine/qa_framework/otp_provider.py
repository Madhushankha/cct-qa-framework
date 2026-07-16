"""
IMAP OTP reader — fetches one-time passcodes from a real mailbox so the
conversation driver can complete OTP-gated chatbot flows (e.g. Flight
Disruption, Name Change) without a human in the loop.

The chatbot triggers an OTP email; this provider polls the configured IMAP
mailbox for a *new* message (received at/after a caller-supplied `since`
timestamp), optionally filtered by sender/subject, extracts the numeric code
with a regex, and returns it. The driver then sends that code as the next
user turn.

Why IMAP (and not the Gmail API): zero Google Cloud project / OAuth-consent
setup. For Gmail, enable 2FA on the test account and create an *app password*
(https://myaccount.google.com/apppasswords) — use that as QA_OTP_APP_PASSWORD,
not the account password.

Design notes:
  * Each scenario runs in its own fresh chat session (see run.py), so OTP state
    is naturally per-scenario. The `since` lower bound is what prevents picking
    up a stale code from an earlier run/turn.
  * IMAP SINCE search has *date* granularity only, so we over-fetch recent
    messages and filter by INTERNALDATE in Python for second-level precision.
  * Newest matching message wins, so a re-sent OTP supersedes an earlier one.
"""

from __future__ import annotations

import email
import html
import imaplib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import Message
from typing import Optional


class OtpError(Exception):
    """Raised when an OTP cannot be retrieved within the timeout."""


def _imap_quote(value: str) -> str:
    """Quote a string for an IMAP search atom (handles embedded quotes/backslashes)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# Default: a standalone run of 4–8 digits. Override per-flow via config/scenario
# when the code length is fixed (tighter regex → fewer false positives).
DEFAULT_OTP_REGEX = r"\b(\d{4,8})\b"


@dataclass
class OtpFilter:
    """Per-fetch matching rules. Falls back to provider defaults when unset."""
    from_contains: Optional[str] = None      # substring match on the From header
    subject_contains: Optional[str] = None   # substring match on the Subject header
    regex: Optional[str] = None              # OTP-extraction regex (group 1 = code)
    body_contains: Optional[str] = None      # require this token in the email body —
                                             # e.g. the passenger name, so concurrent
                                             # sessions sharing one inbox each pick
                                             # only THEIR code (no cross-wiring)


class MailinatorOtpProvider:
    """Reads OTPs from a Mailinator inbox via the v2 REST API.

    Mailinator's private domains (e.g. aircanada.ca) are NOT reachable by IMAP and
    the web password does not authenticate the API — you need a **team API token**
    (Mailinator → Team Settings → API). Pass it as QA_MAILINATOR_TOKEN.

    Same `wait_for_otp(since, otp_filter, timeout)` interface as ImapOtpProvider, so
    it's a drop-in alternative selected by otp.provider == "mailinator".
    """

    BASE = "https://www.mailinator.com/api/v2"

    def __init__(
        self,
        token: str,
        domain: str,
        inbox: str,
        *,
        from_contains: str = "",
        subject_contains: str = "",
        otp_regex: str = DEFAULT_OTP_REGEX,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 5.0,
        skew_buffer_seconds: int = 30,
        on_debug=None,
    ):
        if "@" in inbox and not domain:
            inbox, domain = inbox.split("@", 1)
        if not token or not domain or not inbox:
            raise OtpError(
                "Mailinator OTP provider needs token, domain and inbox "
                "(set QA_MAILINATOR_TOKEN / QA_MAILINATOR_DOMAIN / QA_MAILINATOR_INBOX)."
            )
        self.token = token
        self.domain = domain
        self.inbox = inbox.split("@", 1)[0] if "@" in inbox else inbox
        self.from_contains = from_contains
        self.subject_contains = subject_contains
        self.otp_regex = otp_regex or DEFAULT_OTP_REGEX
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.skew_buffer_seconds = skew_buffer_seconds
        self._on_debug = on_debug

    def _debug(self, tag: str, **payload) -> None:
        if self._on_debug is None:
            return
        try:
            self._on_debug(tag, payload)
        except Exception:
            pass

    def _get(self, path: str) -> dict:
        import json as _json
        import os as _os
        import ssl as _ssl
        import urllib.request
        url = f"{self.BASE}/domains/{self.domain}/inboxes/{self.inbox}{path}"
        req = urllib.request.Request(url, headers={"Authorization": self.token})
        ctx = _ssl.create_default_context()
        if _os.getenv("QA_INSECURE_TLS", "").lower() in ("1", "true", "yes"):
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))

    @staticmethod
    def _msg_epoch(m: dict) -> float:
        # Mailinator messages carry an ms-epoch "time"; fall back to seconds_ago.
        t = m.get("time")
        if isinstance(t, (int, float)) and t > 0:
            return t / 1000.0
        sa = m.get("seconds_ago")
        if isinstance(sa, (int, float)):
            return time.time() - sa
        return 0.0

    def wait_for_otp(
        self,
        since: datetime,
        *,
        otp_filter: Optional[OtpFilter] = None,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        cutoff = (since - timedelta(seconds=self.skew_buffer_seconds)).timestamp()

        f = otp_filter or OtpFilter()
        from_contains = ((f.from_contains if f.from_contains is not None else self.from_contains) or "").lower()
        subject_contains = ((f.subject_contains if f.subject_contains is not None else self.subject_contains) or "").lower()
        regex = re.compile(f.regex or self.otp_regex)
        body_contains = (f.body_contains or "").lower()

        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = time.monotonic() + timeout
        self._debug("otp_wait_start", inbox=f"{self.inbox}@{self.domain}", since=cutoff, timeout=timeout)

        last_err: Optional[Exception] = None
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            try:
                listing = self._get("")
                msgs = listing.get("msgs", []) or []
                # newest first; only messages at/after the cutoff
                fresh = sorted((m for m in msgs if self._msg_epoch(m) >= cutoff),
                               key=self._msg_epoch, reverse=True)
                for m in fresh:
                    if from_contains and from_contains not in (m.get("from", "") or "").lower():
                        continue
                    if subject_contains and subject_contains not in (m.get("subject", "") or "").lower():
                        continue
                    full = self._get(f"/messages/{m.get('id')}")
                    body = self._message_text(full)
                    if body_contains and body_contains not in body.lower():
                        continue
                    hit = regex.search(body)
                    if hit:
                        code = hit.group(1) if hit.groups() else hit.group(0)
                        self._debug("otp_found", code_len=len(code), attempts=attempts)
                        return code
            except Exception as e:
                last_err = e
                self._debug("otp_poll_error", error=str(e), attempt=attempts)
            time.sleep(self.poll_interval_seconds)

        detail = f" (last error: {last_err})" if last_err else ""
        raise OtpError(
            f"No Mailinator OTP matching from~{from_contains!r} subject~{subject_contains!r} "
            f"arrived within {timeout}s in {self.inbox}@{self.domain}{detail}"
        )

    @staticmethod
    def _message_text(full: dict) -> str:
        chunks = []
        for part in full.get("parts", []) or []:
            body = part.get("body") or ""
            headers = part.get("headers", {}) or {}
            ctype = (headers.get("content-type") or "").lower()
            if "html" in ctype:
                body = ImapOtpProvider._html_to_text(body)
            chunks.append(body)
        # some payloads put a flat "body" at the top level too
        if full.get("body"):
            chunks.append(full["body"])
        return "\n".join(chunks)


class ImapOtpProvider:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 993,
        mailbox: str = "INBOX",
        use_ssl: bool = True,
        from_contains: str = "",
        subject_contains: str = "",
        otp_regex: str = DEFAULT_OTP_REGEX,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 5.0,
        skew_buffer_seconds: int = 30,
        on_debug=None,
    ):
        if not host or not username or not password:
            raise OtpError(
                "IMAP OTP provider needs host, username and password "
                "(set QA_OTP_IMAP_HOST / QA_OTP_EMAIL / QA_OTP_APP_PASSWORD)."
            )
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self.use_ssl = use_ssl
        self.from_contains = from_contains
        self.subject_contains = subject_contains
        self.otp_regex = otp_regex or DEFAULT_OTP_REGEX
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        # Tolerate clock skew between this host and the mail server: accept
        # messages whose INTERNALDATE is up to this many seconds before `since`.
        self.skew_buffer_seconds = skew_buffer_seconds
        self._on_debug = on_debug

    # ── debug hook (mirrors AmazonConnectChatClient._debug) ───────────────────

    def _debug(self, tag: str, **payload) -> None:
        if self._on_debug is None:
            return
        try:
            self._on_debug(tag, payload)
        except Exception:
            pass

    # ── public API ────────────────────────────────────────────────────────────

    def wait_for_otp(
        self,
        since: datetime,
        *,
        otp_filter: Optional[OtpFilter] = None,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """
        Poll the mailbox until an OTP from a message received at/after `since`
        is found, or the timeout elapses.

        `since` must be timezone-aware (UTC recommended). Returns the extracted
        code string. Raises OtpError on timeout or connection failure.
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        cutoff = since - timedelta(seconds=self.skew_buffer_seconds)

        f = otp_filter or OtpFilter()
        from_contains = (f.from_contains if f.from_contains is not None else self.from_contains) or ""
        subject_contains = (f.subject_contains if f.subject_contains is not None else self.subject_contains) or ""
        regex = f.regex or self.otp_regex
        body_contains = f.body_contains or ""

        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = time.monotonic() + timeout

        self._debug(
            "otp_wait_start",
            since=cutoff.isoformat(),
            from_contains=from_contains,
            subject_contains=subject_contains,
            timeout=timeout,
        )

        # Hold a single IMAP connection across the whole (possibly multi-minute)
        # poll instead of logging in every interval — far fewer logins, so Gmail
        # won't throttle us. Reconnect only if the connection drops mid-poll.
        last_err: Optional[Exception] = None
        attempts = 0
        conn: Optional[imaplib.IMAP4] = None
        try:
            while time.monotonic() < deadline:
                attempts += 1
                try:
                    if conn is None:
                        conn = self._connect()
                    code = self._search_once(conn, cutoff, from_contains, subject_contains, regex, body_contains)
                    if code:
                        self._debug("otp_found", code_len=len(code), attempts=attempts)
                        return code
                except Exception as e:                   # transient IMAP hiccup
                    last_err = e
                    self._debug("otp_poll_error", error=str(e), attempt=attempts)
                    # Drop the (possibly broken) connection so the next pass reconnects.
                    if conn is not None:
                        try:
                            conn.logout()
                        except Exception:
                            pass
                        conn = None
                time.sleep(self.poll_interval_seconds)
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

        detail = f" (last error: {last_err})" if last_err else ""
        raise OtpError(
            f"No OTP matching from~{from_contains!r} subject~{subject_contains!r} "
            f"arrived within {timeout}s after {cutoff.isoformat()}{detail}"
        )

    # ── one polling pass (on an already-open connection) ───────────────────────

    def _search_once(
        self,
        conn: imaplib.IMAP4,
        cutoff: datetime,
        from_contains: str,
        subject_contains: str,
        regex: str,
        body_contains: str = "",
    ) -> Optional[str]:
        # Re-SELECT each pass so newly-arrived messages become visible on the
        # long-lived connection (a plain re-search wouldn't see them).
        conn.select(self.mailbox)

        # IMAP SINCE is date-granular; use the cutoff's date as a coarse
        # server-side prefilter, then refine by INTERNALDATE below.
        since_date = cutoff.astimezone(timezone.utc).strftime("%d-%b-%Y")
        criteria: list[str] = ["SINCE", since_date]
        # FROM/SUBJECT values must be IMAP-quoted: a bare multi-word value
        # (e.g. "Verify your contact information") makes the server reject
        # the whole command with BAD "Could not parse command".
        if from_contains:
            criteria += ["FROM", _imap_quote(from_contains)]
        if subject_contains:
            criteria += ["SUBJECT", _imap_quote(subject_contains)]

        typ, data = conn.search(None, *criteria)
        if typ != "OK" or not data or not data[0]:
            return None

        ids = data[0].split()
        # Newest first so a re-sent code supersedes an older one.
        candidates: list[tuple[datetime, bytes]] = []
        for msg_id in reversed(ids):
            internal = self._internal_date(conn, msg_id)
            if internal is None or internal < cutoff:
                continue
            candidates.append((internal, msg_id))

        candidates.sort(key=lambda t: t[0], reverse=True)
        pattern = re.compile(regex)
        bc = body_contains.lower()
        for _internal, msg_id in candidates:
            msg = self._fetch_message(conn, msg_id)
            if msg is None:
                continue
            body = self._message_text(msg)
            # Name-scoping for shared inboxes: only accept the email addressed to
            # this session's passenger, so concurrent runs don't grab each other's code.
            if bc and bc not in body.lower():
                continue
            m = pattern.search(body)
            if m:
                return m.group(1) if m.groups() else m.group(0)
        return None

    # ── IMAP helpers ───────────────────────────────────────────────────────────

    def _connect(self) -> imaplib.IMAP4:
        conn: imaplib.IMAP4
        if self.use_ssl:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
        else:
            conn = imaplib.IMAP4(self.host, self.port)
        conn.login(self.username, self.password)
        return conn

    @staticmethod
    def _internal_date(conn: imaplib.IMAP4, msg_id: bytes) -> Optional[datetime]:
        typ, data = conn.fetch(msg_id, "(INTERNALDATE)")
        if typ != "OK" or not data or not data[0]:
            return None
        raw = data[0] if isinstance(data[0], (bytes, bytearray, str)) else data[0][0]
        if isinstance(raw, str):
            raw = raw.encode()
        # Internaldate2tuple parses the full "... INTERNALDATE \"...\"" response
        # and returns a local-time struct_time (the server's zone offset already
        # applied). time.mktime() then yields the correct local epoch.
        parsed = imaplib.Internaldate2tuple(raw)
        if parsed is None:
            return None
        return datetime.fromtimestamp(time.mktime(parsed), tz=None).astimezone(timezone.utc)

    @staticmethod
    def _fetch_message(conn: imaplib.IMAP4, msg_id: bytes) -> Optional[Message]:
        typ, data = conn.fetch(msg_id, "(RFC822)")
        if typ != "OK" or not data:
            return None
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                return email.message_from_bytes(part[1])
        return None

    @staticmethod
    def _html_to_text(html_src: str) -> str:
        """Strip an HTML part down to visible text for OTP matching.

        Crucially removes <style>/<script> blocks *before* dropping tags —
        otherwise CSS literals (e.g. color #005078 → "005078") leak into the
        text and a digit regex can match them ahead of the real code. Then
        strips remaining tags and decodes entities (&nbsp; etc.).
        """
        text = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", html_src)
        text = re.sub(r"<[^>]+>", " ", text)
        return html.unescape(text)

    @classmethod
    def _message_text(cls, msg: Message) -> str:
        """Concatenate text/plain and text/html parts (HTML reduced to text)."""
        chunks: list[str] = []
        parts = msg.walk() if msg.is_multipart() else [msg]
        for part in parts:
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/html":
                text = cls._html_to_text(text)
            chunks.append(text)
        return "\n".join(chunks)
