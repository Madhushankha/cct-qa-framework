"""Render captured chatbot widgets (flight card, info banners, quick replies) as
clean HTML boxes for PO-facing docs — instead of raw [WIDGET:...] JSON blobs.

Capture emits a compact sentinel into the transcript:  §W§<KIND>§<text>
  KIND in {FLIGHT, BANNER, OPTIONS, INFO}.  render_message_html() turns those
into boxes; flight_card_html()/box_html() build richer cards from the full widget."""
import html as _H

SENT = "§W§"


def summarize_widget(inner):
    """Compact, human-readable one-liner for the transcript (no JSON)."""
    wt = (inner.get("wt") or "WIDGET").upper()
    wd = inner.get("wd") or {}
    if wt.startswith("FLIGHT"):
        fl = (wd.get("flights") or [{}])[0]
        fns = " / ".join(s.get("fn", "") for s in (fl.get("segments") or []) if s.get("fn"))
        stops = fl.get("stops")
        stxt = "nonstop" if stops == 0 else (f"{stops} stop" + ("s" if (stops or 0) > 1 else "") if stops is not None else "")
        parts = [fl.get("label", ""), fl.get("date", ""), fns,
                 (f'{fl.get("dep","")}→{fl.get("arr","")}' if fl.get("dep") else ""), stxt]
        return f"{SENT}FLIGHT§" + " · ".join(p for p in parts if p)
    if wt == "QUICK_REPLIES":
        opts = " • ".join(o.get("txt", "") for o in (wd.get("options") or []) if o.get("txt"))
        return f"{SENT}OPTIONS§{opts}"
    if "BANNER" in wt:
        return f"{SENT}BANNER§{wd.get('txt','')}"
    return f"{SENT}INFO§{wd.get('txt','') or wt}"


_STYLES = {
    "FLIGHT": ("#eef5ff", "#1a73a7", "✈️", "Flight"),
    "BANNER": ("#fff8e1", "#c08401", "ℹ️", "Notice"),
    "INFO":   ("#eef7ee", "#2e7d32", "✓", "Info"),
}


def box_html(kind, body):
    b = _H.escape(body or "")
    if kind == "OPTIONS":
        chips = "".join(
            f'<span style="display:inline-block;background:#fff;border:1px solid #ccd;'
            f'border-radius:12px;padding:2px 10px;margin:2px;font-size:12px;color:#555">{_H.escape(o.strip())}</span>'
            for o in (body or "").split("•") if o.strip())
        return f'<div style="margin:4px 0"><span style="font-size:11px;color:#999">options:</span> {chips}</div>'
    bg, bd, icon, label = _STYLES.get(kind, _STYLES["INFO"])
    return (f'<div style="background:{bg};border-left:4px solid {bd};border-radius:6px;'
            f'padding:8px 12px;margin:5px 0;max-width:560px">'
            f'<span style="font-weight:600;color:{bd};font-size:12px">{icon} {label}</span>'
            f'<div style="margin-top:2px">{b}</div></div>')


def render_message_html(text):
    """Turn a message string (possibly containing §W§ sentinels) into HTML:
    plain text stays as text; widget sentinels become boxes/chips."""
    out = []
    for seg in (text or "").split("\n\n"):
        s = seg.strip()
        if not s:
            continue
        if s.startswith(SENT):
            p = s.split("§")
            kind = p[2] if len(p) > 2 else "INFO"
            body = "§".join(p[3:]) if len(p) > 3 else ""
            out.append(box_html(kind, body))
        else:
            out.append(f'<div style="white-space:pre-wrap">{_H.escape(s)}</div>')
    return "".join(out)


def flight_card_html(w):
    """Rich flight card from a full FLIGHT_* widget dict (for the QA report)."""
    wd = w.get("wd") or {}
    cards = []
    for fl in (wd.get("flights") or []):
        seg = " / ".join(s.get("fn", "") for s in (fl.get("segments") or []) if s.get("fn"))
        ori = fl.get("ori") or {}; dest = fl.get("dest") or {}
        stops = fl.get("stops")
        stxt = "nonstop" if stops == 0 else (f"{stops} stop" + ("s" if (stops or 0) > 1 else "") if stops is not None else "")
        cards.append(
            f'<div style="border:1px solid #d0d7de;border-radius:8px;padding:14px;margin:6px 0;max-width:520px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.08)">'
            f'<div style="font-size:17px;font-weight:700">{_H.escape(fl.get("label",""))}'
            f' <span style="color:#777;font-weight:400;font-size:14px">· {_H.escape(fl.get("date",""))}</span></div>'
            f'<div style="margin-top:6px;font-size:14px"><b>{_H.escape(fl.get("dep",""))}</b> {_H.escape(ori.get("code",""))}'
            f' <span style="color:#888">({_H.escape(ori.get("city",""))})</span> &nbsp;→&nbsp; '
            f'<b>{_H.escape(fl.get("arr",""))}</b> {_H.escape(dest.get("code",""))}'
            f' <span style="color:#888">({_H.escape(dest.get("city",""))})</span></div>'
            f'<div style="color:#555;font-size:13px;margin-top:6px">Flight {_H.escape(seg)} · '
            f'{_H.escape(fl.get("dur",""))} · {stxt}</div></div>')
    return "".join(cards)
