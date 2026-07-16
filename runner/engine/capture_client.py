"""AmazonConnectChatClient subclass that ALSO captures widget frames (flight card,
quick-replies, banners) and error bubbles, which the base client drops as empty text.
Used so the harness can verify the flight the bot showed + surface error messages, and
so it can 'click' SINGLE_SELECT / QUICK_REPLIES options like a real web widget.

Vendored from cct-qa-1/fd-int-flow/capture_client.py; the sys.path bootstrap is
replaced with package-relative imports within runner.engine."""
import json

from runner.engine.qa_framework.amazon_connect_client import (
    AmazonConnectChatClient,
    ChatbotError,
)
from runner.engine import widget_render


class CapturingChatClient(AmazonConnectChatClient):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.captured_widgets = []   # raw widget inner-dicts (t == 'w')
        self.captured_errors = []    # bot error bubbles
        self.last_widget = None      # most recent selectable widget {id,wt,src_ref,options,title}
        self._cur_event = {}

    def _extract_bot_text(self, content_raw, content_type):
        # Inspect JSON frames before delegating; capture widgets + error banners.
        if content_raw and "json" in (content_type or ""):
            try:
                inner = json.loads(content_raw)
            except Exception:
                inner = None
            if isinstance(inner, dict):
                t = inner.get("t")
                if t == "w":
                    self.captured_widgets.append(inner)
                    # Capture selectable widgets WITH the message Id so we can answer
                    # SINGLE_SELECT / QUICK_REPLIES by sending the bot's `act` response.
                    wt = inner.get("wt", "")
                    wd = inner.get("wd") or {}
                    opts = [{"id": str(o.get("id")), "txt": o.get("txt", "")}
                            for o in (wd.get("options") or []) if o.get("txt")]
                    if wt in ("SINGLE_SELECT", "QUICK_REPLIES") and opts:
                        self.last_widget = {"id": (self._cur_event or {}).get("Id"),
                                            "src_ref": inner.get("src_ref"), "wt": wt,
                                            "title": wd.get("title", ""), "options": opts}
                    return widget_render.summarize_widget(inner)
                blob = json.dumps(inner).lower()
                if any(m in blob for m in ('"error"', '"failure"', "error_", "failed", "unable")):
                    self.captured_errors.append(inner)
        return AmazonConnectChatClient._extract_bot_text(content_raw, content_type)

    def send_widget_select(self, match):
        """Answer the pending SINGLE_SELECT / QUICK_REPLIES by 'clicking' the option
        whose text best matches `match` — sends the bot's `act` JSON (application/json),
        then returns the bot reply. Mirrors a real button click in the web widget.
        ref = message Id for SINGLE_SELECT, src_ref for QUICK_REPLIES (per live capture)."""
        w = self.last_widget
        if not w:
            raise ChatbotError("no selectable widget pending")
        m = (match or "").lower().strip()
        opt = next((o for o in w["options"] if m and m in o["txt"].lower()), None) \
            or next((o for o in w["options"] if m and o["txt"].lower().startswith(m[:5])), None) \
            or w["options"][0]
        aid = "single_select_submit" if w["wt"] == "SINGLE_SELECT" else "quick_reply_select"
        ref = w["id"] if w["wt"] == "SINGLE_SELECT" else (w["src_ref"] or w["id"])
        act = {"t": "act", "aid": aid, "txt": opt["txt"],
               "sel": [{"id": opt["id"], "txt": opt["txt"]}], "ref": ref}
        self.last_widget = None
        self._send_message(json.dumps(act), content_type="application/json")
        self._log(f"[widget-select] {w['wt']} -> {opt['txt'][:40]}")
        return self._collect_bot_reply()
