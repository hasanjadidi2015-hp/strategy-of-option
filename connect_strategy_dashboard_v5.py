"""
اتصال V5 - داشبورد LIVE4 + V2
ورودی:
  options_dashboard_AHRAM.html (یا LIVE4)
  ahram_strategy_data_v5.json
خروجی:
  options_dashboard_AHRAM_LIVE5.html (LIVE4 + V2)
  options_dashboard_AHRAM_LIVE4.html (overwrite با V2 - اگر کاربر بخواد)
"""

import json
import os
from html import escape

TEMPLATE = "options_dashboard_AHRAM.html"
# همیشه از قالب اصلی استفاده کن، نه LIVE4، تا xlsx.js خراب نشه
# اگر کاربر بخواد LIVE4 رو هم V2 دار کنه، باید جداگانه بگه

DATA_FILE = "ahram_strategy_data_v5.json"
OUTPUT_LIVE5 = "options_dashboard_AHRAM_LIVE5.html"
OUTPUT_LIVE4 = "options_dashboard_AHRAM_LIVE4_V5.html"  # نسخه جدید، LIVE4 اصلی دست نخوره

def fmt(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):,.0f}"
    except:
        return escape(str(value))

def pct(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}%"
    except:
        return "—"

def make_v5_panel(payload):
    cards = []
    for name, data in payload.get("symbols", {}).items():
        if not data.get("available"):
            cards.append(f'<div style="background:#0d1829;border:1px solid #334155;border-radius:13px;padding:14px;color:#94a3b8"><h3 style="margin:0;color:#f8fafc">{escape(name)}</h3><div>داده در دسترس نیست</div></div>')
            continue
        price = data.get("price") or {}
        signal = data.get("signal") or {}
        v2 = data.get("v2_analysis") or {}
        sentiment = data.get("sentiment_v2") or {}
        max_pain = data.get("max_pain") or []
        latest_mp = max_pain[0] if max_pain else {}
        signal_type = signal.get("signal_type") or "—"
        score = signal.get("score")
        v2_score = signal.get("v2_score")
        if v2_score is None and v2:
            v2_score = v2.get("final_score")
        v2_dec = signal.get("v2_decision") or (v2.get("decision") if v2 else "—")
        v2_best = signal.get("v2_best_symbol") or "—"
        if isinstance(v2.get("best_contract"), dict):
            v2_best = v2.get("best_contract", {}).get("symbol", v2_best)

        best_contract = v2.get("best_contract") if v2 else None
        breakdown_html = ""
        risks_html = ""
        if best_contract and isinstance(best_contract, dict):
            breakdown = best_contract.get("breakdown", [])
            if breakdown:
                breakdown_html = '<div style="margin:8px 0;padding:8px;background:#0f172a;border:1px dashed #4c1d95;border-radius:8px;font-size:11px">'
                breakdown_html += '<b style="color:#c4b5fd">🔬 V2 Breakdown:</b><br>'
                for b in breakdown[:5]:
                    breakdown_html += f"<div style='color:#a5b4fc;margin:2px 0'>• {escape(str(b))}</div>"
                breakdown_html += "</div>"
            risks = v2.get("risks", [])
            if risks:
                risks_html = '<div style="margin:8px 0;padding:8px;background:#1a0f1f;border:1px dashed #7f1d1d;border-radius:8px;font-size:11px"><b>⚠️ RISK:</b><br>'
                for r in risks[:2]:
                    risks_html += f"<div style='color:#fca5a5;margin:2px 0'>• {escape(str(r))}</div>"
                risks_html += "</div>"

        # Sentiment
        fg = sentiment.get("fear_greed", {}) if sentiment else {}
        fg_val = fg.get("fear_greed")
        fg_level = fg.get("level", "—")
        fg_opp = fg.get("opportunity", "")
        iran_vix = sentiment.get("iran_vix", {}) if sentiment else {}
        vix_val = iran_vix.get("vix")
        pc = sentiment.get("put_call_ratio", {}) if sentiment else {}
        order_book = data.get("order_book") or sentiment.get("order_book", {}) if sentiment else {}

        sentiment_html = ""
        if fg_val is not None:
            # رنگ بر اساس Fear & Greed
            fg_color = "#22c55e" if fg_val <= 20 else ("#f59e0b" if fg_val >= 80 else "#a78bfa")
            sentiment_html = f'''
            <div style="margin:8px 0;padding:10px;background:linear-gradient(90deg,#1e1b4b,#0f172a);border:1px solid {fg_color};border-radius:10px">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <b style="color:{fg_color}">😱 Fear & Greed Iran: {fmt(fg_val)}/100 {escape(str(fg_level))}</b>
                <span style="background:{fg_color};color:#000;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:bold">{escape(str(fg_opp))}</span>
              </div>
              <div style="margin-top:6px;font-size:11px;color:#cbd5e1">
                Iran VIX: {fmt(vix_val)}% · P/C OI: {fmt(pc.get('pc_oi'))} Vol: {fmt(pc.get('pc_volume'))} · {escape(str(pc.get('sentiment','')))}<br>
                Order: {escape(str(order_book.get('market_state','')))} {fmt(order_book.get('imbalance_pct'))}% {escape(str(order_book.get('pressure','')))}<br>
                {escape(str(fg_opp))}
              </div>
            </div>
            '''

        options_count = len(data.get("options") or [])
        metrics = data.get("chain_metrics") or {}
        iv_hist = data.get("iv_history") or []
        iv_rank_info = f"IV History: {len(iv_hist)} روز" if iv_hist else ""

        mp_line = "Max Pain: —"
        if latest_mp:
            mp_line = f"Max Pain: {fmt(latest_mp.get('max_pain_strike'))} · فاصله {pct(latest_mp.get('distance_pct'))}"

        v2_badge = f"<span style='background:#4c1d95;color:#c4b5fd;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:bold'>V2 {fmt(v2_score)}/100 {escape(str(v2_dec))}</span>" if v2_score is not None else "<span style='background:#243147;color:#94a3b8;border-radius:999px;padding:5px 8px;font-size:11px'>V2 —</span>"

        cards.append(f'''
        <div style="background:linear-gradient(180deg,#1e1b4b,#0d1829);border:1px solid #4c1d95;border-radius:13px;padding:14px;color:#edf3ff">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h3 style="margin:0;font-size:16px;color:#f8fafc">{escape(name)}</h3>
          <div><span style="background:#123c29;color:#86efac;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:bold">{escape(str(signal_type))}</span> {v2_badge}</div></div>
          <div style="font-size:26px;font-weight:900;margin:14px 0 8px;color:#f8fafc">{fmt(price.get('last_price'))}<small style="font-size:11px;color:#94a3b8;margin-right:5px">ریال</small></div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">امتیاز قدیمی <b style="float:left;color:#f8fafc">{fmt(score)}</b></div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#a78bfa;font-size:12px">🔬 CALL SCORE V2 <b style="float:left;color:#a78bfa">{fmt(v2_score)}/100</b> · {escape(str(v2_dec))} · {escape(str(v2_best))}</div>
          {sentiment_html}
          {breakdown_html}
          {risks_html}
          <div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">زنجیره <b style="float:left;color:#f8fafc">{options_count} قرارداد</b></div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">Call/Put Vol <b style="float:left;color:#f8fafc">{fmt(metrics.get('call_volume'))} / {fmt(metrics.get('put_volume'))}</b></div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">OI Ratio <b style="float:left;color:#f8fafc">{fmt(metrics.get('call_put_oi_ratio'))}</b></div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">{escape(mp_line)}</div>
          <div style="border-top:1px solid #334155;padding:8px 0;color:#94a3b8;font-size:11px">{escape(iv_rank_info)} · {escape(str(price.get('time') or '—'))}</div>
        </div>
        ''')

    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    payload_json = payload_json.replace("<", "\\u003c")

    return f'''
    <div id="ahram-bridge-panel-v5" dir="rtl" style="margin:24px auto;padding:20px;max-width:1440px;background:linear-gradient(180deg,#1e1b4b,#111c2e);border:1px solid #4c1d95;border-radius:18px;color:#edf3ff;font-family:Tahoma,Arial,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.3)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:14px;border-bottom:1px solid #4c1d95;padding-bottom:14px;margin-bottom:14px">
        <div><h2 style="margin:0 0 5px;font-size:19px;color:#a78bfa">🔬 AHRAM AI PRO V5 - Option Decision + Sentiment</h2>
        <p style="margin:0;color:#94a3b8;font-size:12px">Greek V2 + IV V2 + Risk V2 + Scoring V2 + Decision V2 + Sentiment V2 (Fear & Greed Iran) · فقط‌خواندنی</p></div>
        <span style="background:#4c1d95;color:#c4b5fd;border-radius:999px;padding:7px 11px;font-size:11px;font-weight:bold">V5 + SENTIMENT</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">{"".join(cards)}</div>
      <div style="margin-top:14px;padding:11px;background:#1e1b4b;color:#c4b5fd;border:1px solid #4c1d95;border-radius:10px;font-size:12px">V5 + Sentiment: Fear & Greed Iran = P/C 30% + Money Flow 25% + Order Book 20% + BPI 15% + News 10% - 0-20 ترس شدید فرصت خرید، 80-100 طمع شدید هشدار سقف. زنجیره مثل قبل کار می‌کند.</div>
      <script id="ahram-bridge-data-v5">window.AHRAM_BRIDGE_DATA_V5 = {payload_json};</script>
      <script id="ahram-chain-loader-v5">
      window.addEventListener("DOMContentLoaded", function () {{
        try {{
          const data = window.AHRAM_BRIDGE_DATA_V5 || {{}};
          const symbols = data.symbols || {{}};
          const calls = [], puts = [];
          const stocks = {{}};
          Object.keys(symbols).forEach(function (name) {{
            const item = symbols[name] || {{}};
            const price = item.price || {{}};
            stocks[name] = Number(price.last_price || price.closing_price || 0);
            (item.options || []).forEach(function (o) {{
              const x = {{
                sym: o.symbol, u: name, S: stocks[name], K: Number(o.strike_price || 0),
                P: Number(o.option_price || 0), last: Number(o.option_price || 0),
                close: Number(o.option_price || 0), expiry: o.expire_date || "",
                days: Number(o.days_to_expire || 0), vol: Number(o.volume || 0),
                bid: 0, ask: 0, live: false, source: "AHRAM V5 SQLite",
                iv: o.implied_volatility, delta: o.delta, gamma: o.gamma, theta: o.theta, vega: o.vega
              }};
              if (String(o.option_type || "").toUpperCase() === "PUT") puts.push(x);
              else calls.push(x);
            }});
          }});
          if (calls.length || puts.length) {{
            if (typeof allStocksMap !== 'undefined') allStocksMap = Object.assign(allStocksMap || {{}}, stocks);
            if (typeof allOptions !== 'undefined') allOptions = calls;
            if (typeof allPuts !== 'undefined') allPuts = puts;
            if (typeof liveOptionQuoteMode !== 'undefined') liveOptionQuoteMode = false;
            if (typeof syncUnderlyingToOptions === 'function') syncUnderlyingToOptions();
            if (typeof buildAllStrategies === 'function') buildAllStrategies();
            if (typeof renderAllPages === 'function') renderAllPages();
            if (typeof renderSymbolDive === 'function') renderSymbolDive();
            if (typeof showToast === 'function') showToast("✅ AHRAM V5 + Sentiment: 6 موتور + زنجیره واقعی بارگذاری شد");
          }}
          console.log("AHRAM V5 + Sentiment Data:", data);
        }} catch (err) {{ console.warn("AHRAM V5 loader:", err); }}
      }});
      </script>
    </div>
    '''

def main():
    global DATA_FILE
    if not os.path.exists(TEMPLATE):
        print(f"قالب پیدا نشد: {TEMPLATE} - از options_dashboard_AHRAM.html استفاده می‌کنم")
        if not os.path.exists("options_dashboard_AHRAM.html"):
            raise FileNotFoundError(f"قالب پیدا نشد: {TEMPLATE}")

    if not os.path.exists(DATA_FILE):
        # اگر V5 نیست، V4 رو تبدیل کن
        if os.path.exists("ahram_strategy_data.json"):
            print(f"{DATA_FILE} پیدا نشد، از ahram_strategy_data.json استفاده می‌کنم")
            DATA_FILE = "ahram_strategy_data.json"
        else:
            raise FileNotFoundError(f"فایل داده پیدا نشد: {DATA_FILE} - اول strategy_bridge_v5.py رو اجرا کن")

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    panel = make_v5_panel(payload)
    # بدون تگ <style> جدا - همه استایل‌ها inline داخل پنل هستن تا CSS به صورت متن نمایش داده نشه

    # تزریق فقط پنل به body
    lower = template.lower()
    body_at = lower.rfind("</body>")
    if body_at < 0:
        raise ValueError("قالب HTML تگ body ندارد")

    output = template[:body_at] + panel + template[body_at:]

    # ذخیره - LIVE4 اصلی دست نخوره، فقط LIVE5 و LIVE4_V5 جدید
    with open(OUTPUT_LIVE5, "w", encoding="utf-8") as f:
        f.write(output)
    with open(OUTPUT_LIVE4, "w", encoding="utf-8") as f:
        f.write(output)

    print("✅ AHRAM LIVE V5 ساخته شد")
    print("OUTPUT LIVE5:", OUTPUT_LIVE5)
    print("OUTPUT LIVE4_V5 (LIVE4 + V2، اصلی دست نخورده):", OUTPUT_LIVE4)
    print("ORIGINAL LIVE4 UNCHANGED: options_dashboard_AHRAM_LIVE4.html")
    print("V5 PANEL: True - 5 موتور جدید فعال")

if __name__ == "__main__":
    main()
