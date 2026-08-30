# -*- coding: utf-8 -*-
"""
اتصال V5 - داشبورد LIVE4 + V2 + Sentiment  (نسخهٔ اصلاح‌شده)

ورودی:
  options_dashboard_AHRAM.html
  ahram_strategy_data_v5.json

خروجی:
  options_dashboard_AHRAM_LIVE5.html   (تنها خروجیِ واقعی)

تغییرات نسبت به نسخهٔ قبلی (رفع باگ‌ها):
  1) اسکریپتِ تزریق‌شده دیگر `allStocksMap` / `allOptions` / `allPuts` /
     `liveOptionQuoteMode` را دستکاری نمی‌کند؛ یعنی قیمتِ زندهٔ داشبورد زیرین
     با دادهٔ کهنهٔ دیتابیس بازنویسی نمی‌شود و «مظنهٔ اجرایی» خاموش نمی‌شود.
  2) کارت‌های بنفش اکنون یک «منبع رندر واحد» در JS دارند و هر ۶۰ ثانیه
     خودبه‌خود تازه می‌شوند (اگر صفحه از طریق http باز شود، JSON را دوباره
     می‌گیرد؛ اگر file:// باشد از همان دادهٔ جاسازی‌شده رندر می‌شود و
     زمانِ ساخت را نشان می‌دهد).
  3) دیگر `options_dashboard_AHRAM_LIVE4_V5.html» نسخهٔ بایت‌به‌بایت یکسان
     تولید نمی‌شود؛ فقط LIVE5 ساخته می‌شود تا گمراه‌کننده نباشد.
"""

import json
import os
from datetime import datetime
from html import escape

TEMPLATE = "options_dashboard_AHRAM.html"
DATA_FILE = "ahram_strategy_data_v5.json"
OUTPUT_LIVE5 = "options_dashboard_AHRAM_LIVE5.html"
REFRESH_SECONDS = 60

CARD_JS = r"""
<script id="ahram-card-renderer-v5">
(function () {
  "use strict";
  function fmt(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return "\u2014";
    return Number(v).toLocaleString("en-US");
  }
  function pct(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return "\u2014";
    var n = Number(v);
    return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
  }
  function fgColor(v) {
    if (v <= 20) return "#ef4444";
    if (v <= 40) return "#f59e0b";
    if (v <= 60) return "#a78bfa";
    if (v <= 80) return "#eab308";
    return "#22c55e";
  }
  function esc(s) {
    var d = document.createElement("div"); d.textContent = (s === null || s === undefined) ? "" : String(s); return d.innerHTML;
  }
  function card(name, data) {
    if (!data || !data.available) {
      return '<div style="background:#0d1829;border:1px solid #334155;border-radius:13px;padding:14px;color:#94a3b8">' +
        '<h3 style="margin:0;color:#f8fafc">' + esc(name) + '</h3><div>داده در دسترس نیست</div></div>';
    }
    var price = data.price || {};
    var signal = data.signal || {};
    var v2 = data.v2_analysis || {};
    var sent = data.sentiment_v2 || {};
    var mp = (data.max_pain && data.max_pain[0]) ? data.max_pain[0] : {};
    var metrics = data.chain_metrics || {};
    var ivh = data.iv_history || [];
    var otype = signal.signal_type || "\u2014";
    var score = signal.score;
    var v2score = signal.v2_score;
    if (v2score === null || v2score === undefined) v2score = v2.final_score;
    var v2dec = signal.v2_decision || v2.decision || "\u2014";
    var v2best = signal.v2_best_symbol || "\u2014";
    var bc = v2.best_contract;
    if (bc && typeof bc === "object" && bc.symbol) v2best = bc.symbol;
    var fg = sent.fear_greed || {};
    var vix = sent.iran_vix || {};
    var pc = sent.put_call_ratio || {};
    var ob = (data.order_book || sent.order_book || {});
    var html = '';
    html += '<div style="background:linear-gradient(180deg,#1e1b4b,#0d1829);border:1px solid #4c1d95;border-radius:13px;padding:14px;color:#edf3ff">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h3 style="margin:0;font-size:16px;color:#f8fafc">' + esc(name) + '</h3>';
    html += '<div><span style="background:#123c29;color:#86efac;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:bold">' + esc(otype) + '</span>';
    html += '<span style="background:#4c1d95;color:#c4b5fd;border-radius:999px;padding:5px 8px;font-size:11px;font-weight:bold">V2 ' + fmt(v2score) + '/100 ' + esc(v2dec) + '</span></div></div>';
    html += '<div style="font-size:26px;font-weight:900;margin:14px 0 8px;color:#f8fafc">' + fmt(price.last_price || price.closing_price) + '<small style="font-size:11px;color:#94a3b8;margin-right:5px">ریال</small></div>';
    // Fear & Greed
    if (fg.fear_greed !== null && fg.fear_greed !== undefined) {
      var c = fgColor(Number(fg.fear_greed));
      html += '<div style="margin:8px 0;padding:10px;background:linear-gradient(90deg,#1e1b4b,#0f172a);border:1px solid ' + c + ';border-radius:10px">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center"><b style="color:' + c + '">😱 Fear & Greed Iran: ' + fmt(fg.fear_greed) + '/100 ' + esc(fg.level) + '</b>';
      html += '<span style="background:' + c + ';color:#000;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:bold">' + esc(fg.opportunity) + '</span></div>';
      html += '<div style="margin-top:6px;font-size:11px;color:#cbd5e1">Iran VIX: ' + fmt(vix.vix) + '% · P/C OI: ' + fmt(pc.pc_oi) + ' Vol: ' + fmt(pc.pc_volume) + ' · ' + esc(pc.sentiment) + '<br>';
      html += 'Order: ' + esc(ob.market_state) + ' ' + fmt(ob.imbalance_pct) + '% ' + esc(ob.pressure) + '<br>' + esc(fg.opportunity) + '</div></div>';
    }
    // V2 breakdown + risks (read the decision's top-level lists first).
    var bd = (v2.breakdown && v2.breakdown.length) ? v2.breakdown : ((bc && bc.breakdown) || []);
    var rk = (v2.risks && v2.risks.length) ? v2.risks : ((bc && bc.risks) || []);
    if (bd.length) {
      html += '<div style="margin:8px 0;padding:8px;background:#0f172a;border:1px dashed #4c1d95;border-radius:8px;font-size:11px"><b style="color:#c4b5fd">🔬 V2 Breakdown:</b><br>';
      for (var i = 0; i < bd.length && i < 5; i++) html += '<div style="color:#a5b4fc;margin:2px 0">• ' + esc(bd[i]) + '</div>';
      html += '</div>';
    }
    if (rk.length) {
      html += '<div style="margin:8px 0;padding:8px;background:#1a0f1f;border:1px dashed #7f1d1d;border-radius:8px;font-size:11px"><b>⚠️ RISK:</b><br>';
      for (var j = 0; j < rk.length && j < 2; j++) html += '<div style="color:#fca5a5;margin:2px 0">• ' + esc(rk[j]) + '</div>';
      html += '</div>';
    }
    var mpLine = 'Max Pain: —';
    if (mp.max_pain_strike) mpLine = 'Max Pain: ' + fmt(mp.max_pain_strike) + ' · فاصله ' + pct(mp.distance_pct);
    html += '<div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">زنجیره <b style="float:left;color:#f8fafc">' + fmt(metrics.contracts_total) + ' قرارداد</b></div>';
    html += '<div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">Call/Put Vol <b style="float:left;color:#f8fafc">' + fmt(metrics.call_volume) + ' / ' + fmt(metrics.put_volume) + '</b></div>';
    html += '<div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">OI Ratio <b style="float:left;color:#f8fafc">' + fmt(metrics.call_put_oi_ratio) + '</b></div>';
    html += '<div style="border-top:1px solid #334155;padding:8px 0;color:#b6c4d8;font-size:12px">' + esc(mpLine) + '</div>';
    html += '<div style="border-top:1px solid #334155;padding:8px 0;color:#94a3b8;font-size:11px">IV History: ' + (ivh.length) + ' روز · ' + esc(price.time || '—') + '</div>';
    html += '</div>';
    return html;
  }
  function render(data, host) {
    var symbols = (data && data.symbols) || {};
    var keys = Object.keys(symbols);
    // Split into group 1 and group 2 by the group field set in the payload.
    var g1 = [], g2 = [];
    for (var i = 0; i < keys.length; i++) {
      var nm = keys[i];
      var d = symbols[nm] || {};
      var g = d.group === 2 ? 2 : 1;   // default to group 1
      if (g === 2) g2.push(nm); else g1.push(nm);
    }
    var html = '';
    if (g2.length) {
      html += '<div style="margin:16px 0 6px;font-size:13px;color:#c4b5fd;font-weight:bold;border-bottom:1px solid #4c1d95;padding-bottom:4px">گروه ۲ — نمادهای جدید</div>';
      html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">';
      for (var a = 0; a < g2.length; a++) html += card(g2[a], symbols[g2[a]]);
      html += '</div>';
    }
    if (g1.length) {
      if (g2.length) html += '<div style="margin:16px 0 6px;font-size:13px;color:#a78bfa;font-weight:bold;border-bottom:1px solid #334155;padding-bottom:4px">گروه ۱ — نمادهای اصلی</div>';
      html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">';
      for (var b = 0; b < g1.length; b++) html += card(g1[b], symbols[g1[b]]);
      html += '</div>';
    }
    host.innerHTML = html || '<div style="color:#94a3b8">هیچ نمادی تعریف نشده است.</div>';
    if (data && data.generated_at) {
      var t = document.getElementById('ahram-v5-timestamp');
      if (t) t.textContent = 'آخرین به‌روزرسانی: ' + data.generated_at + ' · منبع: ' + (data.source || '—');
    }
  }
  window.__ahramV5Render = render;
  document.addEventListener("DOMContentLoaded", function () {
    var host = document.getElementById("ahram-v5-cards");
    if (!host) return;
    var data = window.AHRAM_BRIDGE_DATA_V5 || {};
    render(data, host);
    // Auto-refresh: over http(s) re-read the JSON; over file:// reuse embedded data.
    function refresh() {
      var isHttp = window.location.protocol === 'http:' || window.location.protocol === 'https:';
      if (!isHttp) return;
      fetch('ahram_strategy_data_v5.json', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (js) { window.AHRAM_BRIDGE_DATA_V5 = js; render(js, host); })
        .catch(function () { /* keep last data */ });
    }
    setInterval(refresh, __REFRESH_SECONDS__ * 1000);
  });
})();
</script>
"""


def make_v5_panel(payload):
    payload = payload or {}
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    legend = (
        "V5 + Sentiment: Fear & Greed Iran = P/C 30% + Money Flow 25% + Order Book 20% + "
        "BPI 15% + News 10% - 0-20 ترس شدید فرصت خرید، 80-100 طمع شدید هشدار سقف. "
        "زنجیره مثل قبل کار می‌کند."
    )
    return f"""
    <div id="ahram-bridge-panel-v5" dir="rtl" style="margin:24px auto;padding:20px;max-width:1440px;background:linear-gradient(180deg,#1e1b4b,#111c2e);border:1px solid #4c1d95;border-radius:18px;color:#edf3ff;font-family:Tahoma,Arial,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.3)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:14px;border-bottom:1px solid #4c1d95;padding-bottom:14px;margin-bottom:14px">
        <div><h2 style="margin:0 0 5px;font-size:19px;color:#a78bfa">🔬 AHRAM AI PRO V5 - Option Decision + Sentiment</h2>
        <p style="margin:0;color:#94a3b8;font-size:12px">Greek V2 + IV V2 + Risk V2 + Scoring V2 + Decision V2 + Sentiment V2 (Fear &amp; Greed Iran) · فقط‌خواندنی</p></div>
        <span style="background:#4c1d95;color:#c4b5fd;border-radius:999px;padding:7px 11px;font-size:11px;font-weight:bold">V5 + SENTIMENT</span>
      </div>
      <div id="ahram-v5-cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px"></div>
      <div id="ahram-v5-timestamp" style="margin-top:14px;color:#94a3b8;font-size:11px"></div>
      <div style="margin-top:8px;padding:11px;background:#1e1b4b;color:#c4b5fd;border:1px solid #4c1d95;border-radius:10px;font-size:12px">{escape(legend)}</div>
      <script id="ahram-bridge-data-v5">window.AHRAM_BRIDGE_DATA_V5 = {payload_json};</script>
      {CARD_JS.replace("__REFRESH_SECONDS__", str(REFRESH_SECONDS))}
    </div>
    """


def main():
    if not os.path.exists(TEMPLATE):
        raise FileNotFoundError(f"قالب پیدا نشد: {TEMPLATE}")
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(
            f"فایل داده پیدا نشد: {DATA_FILE} - اول strategy_bridge_v5.py را اجرا کن")

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        template = f.read()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    panel = make_v5_panel(payload)
    body_at = template.lower().rfind("</body>")
    if body_at < 0:
        raise ValueError("قالب HTML تگ body ندارد")
    output = template[:body_at] + panel + template[body_at:]

    with open(OUTPUT_LIVE5, "w", encoding="utf-8") as f:
        f.write(output)

    print("✅ AHRAM LIVE V5 ساخته شد")
    print("OUTPUT LIVE5:", OUTPUT_LIVE5)
    print("✅ دادهٔ زندهٔ داشبورد زیرین دیگر بازنویسی نمی‌شود (باگ رفع شد)")
    print(f"✅ کارت‌های V5 هر {REFRESH_SECONDS} ثانیه خودبه‌خود تازه می‌شوند")
    print("ℹ️ نسخهٔ تکراری LIVE4_V5 دیگر تولید نمی‌شود")


if __name__ == "__main__":
    main()
