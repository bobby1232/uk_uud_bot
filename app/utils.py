from __future__ import annotations
from datetime import date, datetime, timedelta, time
from typing import List, Tuple
import re

def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))

def format_date_btn(d: date) -> str:
    # RU weekdays short
    ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    wd = ru[d.weekday()]
    return f"{wd} {d.strftime('%d.%m')}"

def date_range(horizon_days: int) -> List[date]:
    today = date.today()
    return [today + timedelta(days=i) for i in range(0, max(1, horizon_days) + 1)]

def generate_slots(start_hhmm: str, end_hhmm: str, slot_min: int) -> List[Tuple[str,str]]:
    start = parse_hhmm(start_hhmm)
    end = parse_hhmm(end_hhmm)

    def to_minutes(t: time) -> int:
        return t.hour*60 + t.minute

    def from_minutes(x: int) -> time:
        return time(x//60, x%60)

    s = to_minutes(start)
    e = to_minutes(end)
    out = []
    cur = s
    while cur + slot_min <= e:
        a = from_minutes(cur)
        b = from_minutes(cur + slot_min)
        out.append((a.strftime("%H:%M"), b.strftime("%H:%M")))
        cur += slot_min
    return out

def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if len(digits) < 10:
        return None
    # keep original-ish but normalized to +<digits> if starts with 7/8 and len 11
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    return "+" + digits

STATUS_LABEL = {
    "CREATED": "Создана",
    "IN_PROGRESS": "В работе",
    "DONE": "Выполнена",
    "ARCHIVED": "Архив",
}
