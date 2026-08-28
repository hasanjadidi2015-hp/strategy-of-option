# -*- coding: utf-8 -*-
"""
Jalali (Persian) calendar + helper date math for the AHRAM V5 collector.
Pure Python — no external libraries, so it works on any Windows/Python 3.10+.
Port of the well-known jalaali-js algorithm (MIT). Validated against ICU for
2015–2035 in the test suite.
"""
from __future__ import annotations
from datetime import date, datetime

_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635,
           2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _div(a: int, b: int) -> int:
    return int(a / b) if a >= 0 else -int(-a // b)


def _mod(a: int, b: int) -> int:
    return a - _div(a, b) * b


def _jal_cal(jy: int):
    gy = jy + 621
    leap_j, jp, jump = -14, _BREAKS[0], 0
    for i in range(1, len(_BREAKS)):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j = leap_j + _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn: int):
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _d2j(jdn: int):
    gy, _, _ = _d2g(jdn)
    jy = gy - 621
    leap, gy2, march = _jal_cal(jy)
    k = jdn - _g2d(gy2, 3, march)
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def j2d(jy: int, jm: int, jd: int) -> int:
    """Jalali date -> (proleptic) Julian day number."""
    leap, gy, march = _jal_cal(jy)
    return _g2d(gy, 3, march) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    return _d2j(_g2d(gy, gm, gd))


def jalali_to_gregorian(jy: int, jm: int, jd: int):
    return _d2g(j2d(jy, jm, jd))


def jalali_str(gy: int, gm: int, gd: int) -> str:
    y, m, d = _d2j(_g2d(gy, gm, gd))
    return f"{y}/{m:02d}/{d:02d}"


def today_tehran(now: datetime | None = None) -> str:
    """Today's date as a Jalali string in the Asia/Tehran timezone."""
    if now is None:
        # The built-in timezone database always has Asia/Tehran on modern Python.
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Tehran"))
        except Exception:
            # Fallback: use UTC+3:30 fixed offset (Iran is +03:30).
            from datetime import timedelta
            now = datetime.utcnow() + timedelta(hours=3, minutes=30)
    return jalali_str(now.year, now.month, now.day)


def normalize_expiry(value) -> str:
    """Turn TSETMC expiry text into a padded 'YYYY/MM/DD' Jalali date."""
    if not value:
        return ""
    s = str(value).strip()
    p = s.split("/")
    if len(p) == 3:
        y, m, d = p
        yy = int(y) if y.isdigit() else 0
        if yy < 100:
            yy += 1400 if yy < 80 else 1300
        return f"{yy}/{int(m):02d}/{int(d):02d}" if m.isdigit() and d.isdigit() else s
    if len(s) == 8 and s.isdigit():
        yy = int(s[:4])
        return f"{yy}/{int(s[4:6]):02d}/{int(s[6:8]):02d}"
    return s


def days_to_expiry(expiry: str, today: str | None = None) -> int:
    """Whole calendar days until `expiry` (a Jalali date) relative to `today`."""
    if today is None:
        today = today_tehran()
    a = parse_jalali(today)
    b = parse_jalali(expiry)
    if not a or not b:
        return 0
    da = date(*jalali_to_gregorian(*a))
    db = date(*jalali_to_gregorian(*b))
    return (db - da).days


def parse_jalali(value: str):
    try:
        y, m, d = [int(x) for x in str(value).strip().split("/")[:3]]
    except Exception:
        return None
    try:
        return y, m, d
    except Exception:
        return None
