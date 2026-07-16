"""
AmazonConnectChatClient — Amazon Connect customer-chat protocol.

Vendored from cct-qa-1. The only change from the source is that ``boto3`` and
``websocket`` are imported LAZILY (inside __init__ / the methods that use them),
like seed/source.py's connect(), so that importing this module — and everything
that imports it (runner.engine.flow, runner.build) — succeeds OFFLINE with only
the base deps. The live extra (boto3, websocket-client) is needed only to actually
drive a session.

Flow:
  1. POST <start_chat_url>  (your API Gateway)  ->  ParticipantToken
  2. connectparticipant.create_participant_connection(ParticipantToken)
        -> ConnectionToken + WebSocket URL  (AWS SigV4 signed by boto3)
  3. Open WebSocket -> send aws/subscribe frame
  4. connectparticipant.send_message(ConnectionToken, text)
  5. Read WebSocket frames until an AGENT/BOT MESSAGE event arrives
  6. Close WebSocket
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from .config import cfg, ChatbotConfig


# Callable shape for the debug-trace hook: (tag, payload-dict). None = disabled.
DebugCallback = Optional[Callable[[str, dict[str, Any]], None]]


# QA_INSECURE_TLS=1 disables certificate verification on the three outbound legs
# this client makes. Workaround for TLS-inspecting middleboxes only; default OFF.
_INSECURE_TLS = os.getenv("QA_INSECURE_TLS", "").lower() in ("1", "true", "yes")
if _INSECURE_TLS:
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    print(
        "[WARN] QA_INSECURE_TLS=1 — TLS certificate verification is DISABLED "
        "for Amazon Connect calls. Workaround use only."
    )


class ChatbotError(Exception):
    """Raised on any failure talking to Amazon Connect."""


class AmazonConnectChatClient:
    def __init__(
        self,
        config: ChatbotConfig | None = None,
        on_debug: DebugCallback = None,
    ):
        import boto3  # lazy: keeps the module import offline-safe (live extra only)

        c = config if config is not None else cfg.chatbot
        self._on_debug = on_debug
        self.start_chat_url = c.base_url.rstrip("/") + c.endpoint_path
        self.region = c.region
        self.init_payload = c.init_payload
        self.response_timeout = c.response_timeout_seconds
        self.http_timeout = c.timeout_seconds
        self.api_key = c.api_key

        # Customer-side APIs are authenticated via ParticipantToken/ConnectionToken
        # in the payload; the request envelope is still SigV4-signed by boto3 with
        # empty credentials (matching amazon-connect-chatjs in the browser).
        self.client = boto3.client(
            "connectparticipant",
            region_name=self.region,
            aws_access_key_id="",
            aws_secret_access_key="",
            verify=not _INSECURE_TLS,
        )

        self.contact_id: Optional[str] = None
        self.participant_id: Optional[str] = None
        self.participant_token: Optional[str] = None
        self.connection_token: Optional[str] = None
        self.websocket_url: Optional[str] = None
        self.ws = None
        self._greeting_text: str = ""
        # Frame-faithful log of EVERY inbound bot MESSAGE frame, in order.
        self.all_bot_frames: list = []

    # -- Per-session log prefix -----------------------------------------------

    def _log(self, msg: str) -> None:
        tag = self.contact_id or f"tmp-{id(self):x}"
        print(f"[ContactId={tag}] {msg}")

    # -- Debug trace hook -----------------------------------------------------

    def _debug(self, tag: str, **payload: Any) -> None:
        if self._on_debug is None:
            return
        try:
            self._on_debug(tag, payload)
        except Exception as e:
            self._log(f"[debug-cb] failed: {e}")

    # -- Public API -----------------------------------------------------------

    def start_session(self) -> None:
        self._start_chat()
        self._create_participant_connection()
        self._open_websocket()
        self._subscribe()
        self._wait_for_bot_ready()

    def ask(self, query: str, session_id: str = "") -> str:
        if not self.connection_token:
            self.start_session()
        self._debug("send_query", text=query)
        self._send_message(query)
        reply = self._collect_bot_reply()
        self._debug("reply_complete", length=len(reply), preview=reply[:300])

        if self._reply_is_only_greeting(reply):
            raise ChatbotError(
                "Bot returned only its greeting — query was not processed. "
                f"Captured reply: {reply[:200]}"
            )
        return reply

    def _reply_is_only_greeting(self, reply: str) -> bool:
        if not reply:
            return True
        norm = lambda s: " ".join(s.lower().split())
        r = norm(reply)
        g = norm(self._greeting_text)
        if g and r in g:
            return True
        if len(reply.strip()) < 120:
            markers = (
                "how can i help", "how may i help", "virtual assistant",
                "i will be your", "happy to help",
            )
            if any(m in r for m in markers) and not any(c.isdigit() for c in r):
                return True
        return False

    # -- Wait for bot greeting to finish before sending the real query --------

    def _wait_for_bot_ready(
        self,
        quiet_seconds: float = 60.0,
        max_wait: float = 120.0,
        min_wait: float = 10.0,
    ) -> None:
        import websocket  # lazy

        deadline = time.time() + max_wait
        started_at = time.time()
        last_activity = started_at
        seen_bot_msg = False
        original_timeout = self.ws.gettimeout()
        self.ws.settimeout(1.0)

        self._log("[wait] draining bot greeting frames...")
        self._greeting_text = ""
        try:
            while time.time() < deadline:
                try:
                    raw = self.ws.recv()
                    if raw:
                        last_activity = time.time()
                        event = self._parse_frame(raw)
                        if event:
                            evt_type = event.get("Type") or ""
                            role = event.get("ParticipantRole") or ""
                            if evt_type == "MESSAGE" and role in self.BOT_ROLES:
                                seen_bot_msg = True
                                content_type = event.get("ContentType", "")
                                content_raw = event.get("Content", "")
                                self._cur_event = event
                                text = self._extract_bot_text(content_raw, content_type)
                                if text:
                                    self._greeting_text += text + "\n"
                                    self._note_frame(event, text)
                        self._log(f"[greeting drained] {raw[:120]}...")
                except websocket.WebSocketTimeoutException:
                    quiet = time.time() - last_activity
                    elapsed = time.time() - started_at
                    if seen_bot_msg and quiet >= quiet_seconds:
                        break
                    if not seen_bot_msg and elapsed >= min_wait and quiet >= quiet_seconds:
                        break
        finally:
            self.ws.settimeout(original_timeout or self.response_timeout)
        self._log(f"[wait] bot ready (seen_bot_msg={seen_bot_msg})")
        self._debug(
            "greeting_drained",
            seen_bot_msg=seen_bot_msg,
            greeting_preview=self._greeting_text[:300],
            wait_seconds=round(time.time() - started_at, 1),
        )

    def end_chat(self) -> None:
        if not self.connection_token:
            self._debug("end_chat_skipped", reason="no active session")
            return
        try:
            self.client.send_message(
                Content="end chat",
                ContentType="text/plain",
                ConnectionToken=self.connection_token,
            )
            self._log("[end-chat] sent terminator message")
            self._debug("end_chat_sent", contact_id=self.contact_id)
        except Exception as e:
            self._log(f"[end-chat] best-effort send failed: {e}")
            self._debug("end_chat_failed", contact_id=self.contact_id, error=str(e))

    def close(self) -> None:
        self.end_chat()
        if self.ws is not None:
            try:
                self.ws.close()
                self._log("[session] WebSocket closed")
                self._debug("ws_closed", contact_id=self.contact_id)
            except Exception as e:
                self._debug("ws_close_failed", contact_id=self.contact_id, error=str(e))
            self.ws = None

    # -- Step 1: POST /start-chat ---------------------------------------------

    def _start_chat(self) -> None:
        payload = json.dumps(self.init_payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        req = urllib.request.Request(
            self.start_chat_url, data=payload, headers=headers, method="POST"
        )

        # Amazon Connect StartChatContact is rate-limited (HTTP 429) and 5xx is a
        # transient AWS blip; retry both with exponential backoff + jitter.
        import random
        max_attempts = 10
        base_delay = 5.0
        data = None
        ssl_ctx = ssl._create_unverified_context() if _INSECURE_TLS else None
        self._debug("start_chat_request", url=self.start_chat_url, insecure_tls=_INSECURE_TLS)
        for attempt in range(max_attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.http_timeout, context=ssl_ctx) as resp:
                    data = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                retryable = e.code == 429 or 500 <= e.code < 600
                if retryable and attempt < max_attempts - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 2.0), 60)
                    self._log(f"[start-chat] HTTP {e.code}; retry in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{max_attempts})")
                    time.sleep(delay)
                    continue
                raise ChatbotError(f"start-chat HTTP {e.code}: {body}") from e
            except urllib.error.URLError as e:
                if attempt < max_attempts - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 2.0), 60)
                    self._log(f"[start-chat] network error: {e.reason}; retry in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{max_attempts})")
                    time.sleep(delay)
                    continue
                raise ChatbotError(f"start-chat network error: {e.reason}") from e

        result = data.get("data", {}).get("startChatResult", {})
        self.contact_id = result.get("ContactId")
        self.participant_id = result.get("ParticipantId")
        self.participant_token = result.get("ParticipantToken")

        if not self.participant_token:
            raise ChatbotError(
                f"ParticipantToken missing from /start-chat response. Got keys: {list(result.keys())}"
            )
        self._log(f"[session] start-chat OK ParticipantId={self.participant_id}")
        self._debug(
            "start_chat_response",
            contact_id=self.contact_id,
            participant_id=self.participant_id,
            has_participant_token=bool(self.participant_token),
        )

    # -- Step 2: CreateParticipantConnection (boto3-signed) -------------------

    def _create_participant_connection(self) -> None:
        from botocore.exceptions import BotoCoreError, ClientError  # lazy

        try:
            resp = self.client.create_participant_connection(
                Type=["WEBSOCKET", "CONNECTION_CREDENTIALS"],
                ParticipantToken=self.participant_token,
            )
        except (ClientError, BotoCoreError) as e:
            raise ChatbotError(f"CreateParticipantConnection failed: {e}") from e

        self.websocket_url = resp["Websocket"]["Url"]
        self.connection_token = resp["ConnectionCredentials"]["ConnectionToken"]
        ws_host = self.websocket_url.split("?", 1)[0]
        ct_preview = (self.connection_token[:8] + "...") if self.connection_token else "none"
        self._log(f"[session] participant connection OK ConnectionToken={ct_preview} ws_host={ws_host}")
        self._debug(
            "participant_connection_created",
            contact_id=self.contact_id,
            connection_token_preview=ct_preview,
            ws_host=ws_host,
        )

    # -- Step 3 + 4: WebSocket + subscribe ------------------------------------

    def _open_websocket(self) -> None:
        import websocket  # lazy

        self.ws = websocket.WebSocket()
        ws_kwargs: dict = {"timeout": self.http_timeout}
        if _INSECURE_TLS:
            ws_kwargs["sslopt"] = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        self.ws.connect(self.websocket_url, **ws_kwargs)
        self.ws.settimeout(self.response_timeout)
        self._debug("ws_opened")

    def _subscribe(self) -> None:
        frame = {"topic": "aws/subscribe", "content": {"topics": ["aws/chat"]}}
        self.ws.send(json.dumps(frame))
        try:
            self.ws.recv()           # drain subscribe-success frame
        except Exception:
            pass
        self._debug("ws_subscribed")

    # -- Step 5: SendMessage (boto3-signed) -----------------------------------

    def _send_message(self, text: str, content_type: str = "text/plain") -> None:
        from botocore.exceptions import BotoCoreError, ClientError  # lazy

        try:
            self.client.send_message(
                Content=text,
                ContentType=content_type,
                ConnectionToken=self.connection_token,
            )
        except (ClientError, BotoCoreError) as e:
            raise ChatbotError(f"SendMessage failed: {e}") from e

    # Hook: called for every bot MESSAGE frame that extracted to NO text.
    def _capture_widget(self, event: dict, content_raw: str, content_type: str) -> None:
        pass

    # -- Step 6: collect bot reply from WebSocket -----------------------------

    # Roles that represent the chatbot/agent (anything that isn't the customer).
    BOT_ROLES = {"AGENT", "SYSTEM", "BOT", "CUSTOM_BOT"}

    # Terminal quiet window — once bot sends no frames for this long after a
    # MESSAGE, we treat the reply as complete. Handles multi-frame responses.
    REPLY_QUIET_SECONDS = 3.0

    def _note_frame(self, event, text) -> None:
        self.all_bot_frames.append({
            "id": event.get("Id"),
            "ts": event.get("AbsoluteTime"),
            "text": text or "",
            "ct": event.get("ContentType", ""),
        })

    def _collect_bot_reply(self) -> str:
        import websocket  # lazy

        deadline = time.time() + self.response_timeout
        chunks: list[str] = []
        frame_count = 0
        last_message_time: Optional[float] = None
        last_widget_time: Optional[float] = None

        original_timeout = self.ws.gettimeout()
        self.ws.settimeout(1.0)

        try:
            while time.time() < deadline:
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    if chunks and last_message_time and (time.time() - last_message_time) >= self.REPLY_QUIET_SECONDS:
                        break
                    if not chunks and last_widget_time and (time.time() - last_widget_time) >= self.REPLY_QUIET_SECONDS:
                        break
                    continue
                except Exception as e:
                    raise ChatbotError(f"WebSocket receive error: {e}") from e

                if not raw:
                    continue

                frame_count += 1
                event = self._parse_frame(raw)
                if event is None:
                    continue

                event_type = event.get("Type") or ""
                content_type = event.get("ContentType", "")
                role = event.get("ParticipantRole", "")
                content_raw = event.get("Content", "")

                self._log(f"[frame #{frame_count}] type={event_type!r} ct={content_type!r} role={role!r}")

                if role == "CUSTOMER" or event_type != "MESSAGE" or role not in self.BOT_ROLES:
                    continue

                self._cur_event = event
                text = self._extract_bot_text(content_raw, content_type)
                if text:
                    self._log(f"[bot reply chunk] {text[:200]}")
                    self._debug("reply_chunk", length=len(text), preview=text[:300])
                    chunks.append(text)
                    self._note_frame(event, text)
                    last_message_time = time.time()
                else:
                    last_widget_time = time.time()
        finally:
            self.ws.settimeout(original_timeout or self.response_timeout)

        if not chunks:
            raise ChatbotError(
                f"No bot reply received within {self.response_timeout}s "
                f"({frame_count} frames observed)"
            )
        return "\n\n".join(chunks)

    # -- Frame + content parsers ----------------------------------------------

    @staticmethod
    def _parse_frame(raw: str) -> Optional[dict]:
        """Extract the inner event dict from an Amazon Connect WebSocket frame."""
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            return None

        content_raw = frame.get("content")
        if isinstance(content_raw, str):
            try:
                return json.loads(content_raw)
            except json.JSONDecodeError:
                return None
        if isinstance(content_raw, dict):
            return content_raw
        return frame

    @staticmethod
    def _extract_bot_text(content_raw: str, content_type: str) -> str:
        if not content_raw:
            return ""

        if content_type in ("text/plain", "text/markdown") or "markdown" in content_type:
            return content_raw

        if "json" in content_type:
            try:
                inner = json.loads(content_raw)
            except json.JSONDecodeError:
                return content_raw

            if not isinstance(inner, dict):
                return str(inner)

            t = inner.get("t")
            if t == "md":
                return inner.get("md", "")
            if t == "txt":
                return inner.get("txt", "")
            if t == "w":
                return ""   # widget/banner — skip

            for v in inner.values():
                if isinstance(v, str):
                    return v
            return ""

        return content_raw
