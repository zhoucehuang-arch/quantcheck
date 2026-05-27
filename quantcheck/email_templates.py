from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Mapping


def build_card_email_html(title: str, cards: list[Mapping[str, Any]], context: str = "system") -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value or ""))

    def card(item: Mapping[str, Any]) -> str:
        tone = str(item.get("tone") or "neutral")
        border = "#d7e3da"
        value_color = "#16a34a"
        if tone == "error":
            border = "#fecaca"
            value_color = "#b91c1c"
        elif tone == "warning":
            border = "#fde68a"
            value_color = "#a16207"
        return f"""
              <tr>
                <td style=\"padding:0 0 10px 0;\">
                  <div style=\"display:block;border:1px solid {border};border-radius:12px;background:#ffffff;padding:12px 13px;\">
                    <div style=\"font-size:11px;line-height:1.25;color:#64748b;text-transform:uppercase;letter-spacing:.04em;\">{esc(item.get('label'))}</div>
                    <div style=\"font-size:14px;line-height:1.45;color:{value_color};font-weight:800;word-break:break-word;white-space:pre-wrap;margin-top:5px;\">{esc(item.get('value'))}</div>
                  </div>
                </td>
              </tr>"""

    body = "".join(card(item) for item in cards)
    return f"""<!doctype html>
<html>
  <body style=\"margin:0;padding:0;background:#f6f8f7;font-family:Arial,Helvetica,sans-serif;color:#0f172a;\">
    <div style=\"max-width:680px;margin:0 auto;padding:12px 8px;\">
      <div style=\"background:#ffffff;border:1px solid #d7e3da;border-radius:16px;padding:18px 14px;\">
        <div style=\"font-size:12px;color:#16a34a;font-weight:700;letter-spacing:.06em;text-transform:uppercase;\">Quant GT Monitor</div>
        <h1 style=\"font-size:24px;line-height:1.2;margin:6px 0 8px 0;color:#0f172a;\">{esc(title)}</h1>
        <div style=\"font-size:13px;color:#64748b;line-height:1.5;margin-bottom:14px;\">Context: {esc(context)}<br>Generated: {esc(datetime.now(timezone.utc).isoformat())}</div>
        <table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;width:100%;font-size:15px;line-height:1.4;\">
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>
  </body>
</html>"""
