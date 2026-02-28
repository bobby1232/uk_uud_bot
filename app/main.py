from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date, time
import re

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode

from .config import settings
from .db import DB
from . import texts
from .keyboards import (
    consent_kb, menu_kb, address_kb, categories_kb, services_kb, dates_kb,
    slots_kb, phone_kb, rating_kb, admin_status_kb, price_confirm_kb,
    astro_time_mode_kb, astro_goal_kb, astro_tz_confirm_kb, astro_confirm_kb, astro_packages_kb
)
from .utils import date_range, generate_slots, parse_hhmm, normalize_phone, STATUS_LABEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("uk_bot")

db = DB(settings.DATABASE_URL)

# ---------- Helpers ----------
def new_draft(step: str) -> dict:
    return {"step": step}

def draft_step(d: dict | None) -> str | None:
    return d.get("step") if d else None

def format_dt_ru(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M")

def build_group_card(req: dict, slots: list[tuple[str,str]], rating: dict | None) -> str:
    status_label = STATUS_LABEL.get(req["status"], req["status"])
    lines = []
    lines.append(f"**Заявка №{req['id']} — {status_label}**")
    lines.append(f"Услуга: {req['category_name_snapshot']} / {req['service_name_snapshot']}")
    if req.get("apartment"):
        lines.append(f"Адрес: {req['address_label']}, кв. {req['apartment']}")
    else:
        lines.append(f"Адрес: {req['address_label']}")
    lines.append(f"Дата: {req['booking_date'].strftime('%d.%m.%Y')}")
    lines.append('Интервалы: ' + ", ".join([f"{a}–{b}" for a,b in slots]))
    lines.append(f"Сумма: {req['price_snapshot_rub']} ₽")
    # profile fields aren't stored on request; they live in user_profiles. But we captured them in draft during create.
    # For group card we rely on snapshots stored nowhere; simplest: store in request via address_label only.
    # Workaround: draft includes full_name/phone, but after create it's gone.
    # Solution: keep minimal: we include telegram_user_id and fetch profile live is additional query. We'll do it.
    return "\n".join(lines)

async def fetch_profile(telegram_user_id: int) -> tuple[str|None, str|None]:
    assert db.pool
    r = await db.pool.fetchrow("SELECT full_name, phone FROM user_profiles WHERE telegram_user_id=$1", telegram_user_id)
    if not r:
        return None, None
    return r["full_name"], r["phone"]

async def build_group_card_full(req: dict) -> str:
    slots = await db.get_request_slots(req["id"])
    rating = await db.get_request_rating(req["id"])
    history = await db.get_request_status_history(req["id"])
    status_label = STATUS_LABEL.get(req["status"], req["status"])
    full_name, phone = await fetch_profile(req["telegram_user_id"])
    lines = []
    lines.append(f"**Заявка №{req['id']} — {status_label}**")
    lines.append(f"Услуга: {req['category_name_snapshot']} / {req['service_name_snapshot']}")
    if req.get("apartment"):
        lines.append(f"Адрес: {req['address_label']}, кв. {req['apartment']}")
    else:
        lines.append(f"Адрес: {req['address_label']}")
    lines.append(f"Дата: {req['booking_date'].strftime('%d.%m.%Y')}")
    lines.append('Интервалы: ' + ", ".join([f"{a}–{b}" for a,b in slots]))
    lines.append(f"Сумма: {req['price_snapshot_rub']} ₽")
    if req.get("pending_status") == "IN_PROGRESS" and req.get("pending_price_rub"):
        asked_at = format_dt_ru(req.get("pending_status_requested_at"))
        lines.append(f"⏳ Ожидает подтверждения клиента: {req['pending_price_rub']} ₽ (запрошено {asked_at})")
    if full_name:
        lines.append(f"Клиент: {full_name}")
    if phone:
        lines.append(f"Телефон: {phone}")
    if history:
        lines.append("История статусов:")
        for item in history:
            lines.append(f"• {STATUS_LABEL.get(item['status'], item['status'])}: {format_dt_ru(item['changed_at'])}")
    if rating:
        comment = (rating.get("comment") or "").strip()
        if comment:
            lines.append(f"Оценка: {rating['stars']}/5 — {comment}")
        else:
            lines.append(f"Оценка: {rating['stars']}/5")
    return "\n".join(lines)


# ---------- Bot ----------


def parse_birth_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_timezone(raw: str) -> str | None:
    value = raw.strip().upper().replace(" ", "")
    if re.fullmatch(r"UTC[+-](?:[0-9]|1[0-4])", value):
        return value
    return None


def zodiac_sign(birth_date: date) -> str:
    m, d = birth_date.month, birth_date.day
    signs = [
        ((1, 20), "Козерог"), ((2, 19), "Водолей"), ((3, 21), "Рыбы"), ((4, 20), "Овен"),
        ((5, 21), "Телец"), ((6, 21), "Близнецы"), ((7, 23), "Рак"), ((8, 23), "Лев"),
        ((9, 23), "Дева"), ((10, 23), "Весы"), ((11, 22), "Скорпион"), ((12, 22), "Стрелец"),
        ((12, 32), "Козерог"),
    ]
    for (sm, sd), sign in signs:
        if (m, d) < (sm, sd):
            return sign
    return "Козерог"


def pseudo_moon_sign(birth_date: date) -> str:
    moon = ["Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева", "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"]
    idx = (birth_date.toordinal() // 3) % len(moon)
    return moon[idx]


def build_astro_passport(d: dict) -> str:
    birth_date = date.fromisoformat(d["birth_date"])
    sun = zodiac_sign(birth_date)
    moon = pseudo_moon_sign(birth_date)
    mode = d.get("birth_time_mode")
    asc = "не рассчитывается в режиме без времени" if mode == "UNKNOWN" else f"условно {sun}"
    goal = d.get("goal", "Самореализация")

    strengths = {
        "Овен": "инициативность и смелые старты",
        "Телец": "устойчивость и умение доводить до результата",
        "Близнецы": "гибкость мышления и коммуникация",
        "Рак": "эмпатия и внутренняя чуткость",
        "Лев": "харизма и лидерский импульс",
        "Дева": "системность и внимание к деталям",
        "Весы": "дипломатия и баланс интересов",
        "Скорпион": "глубина и трансформационная сила",
        "Стрелец": "видение перспективы и вера",
        "Козерог": "дисциплина и стратегичность",
        "Водолей": "оригинальность и независимость",
        "Рыбы": "интуиция и образное мышление",
    }
    blind = {
        "Отношения": "идеализация партнера вместо честного диалога",
        "Карьера": "переработка и завышенная планка к себе",
        "Деньги": "эмоциональные решения вместо стратегии",
        "Самореализация": "страх публичности и откладывание первых шагов",
        "Период": "расфокус на множестве задач",
        "Другое": "недооценка своих ресурсов",
    }
    month_theme = f"наводить порядок в теме «{goal.lower()}» и фиксировать промежуточные результаты"
    mini_insight = "ваш быстрый рост начинается там, где вы называете цель вслух и делите её на 3 шага"

    return texts.ASTRO_PASSPORT.format(
        sun=sun,
        moon=moon,
        asc=asc,
        strength=strengths.get(sun, "внутренняя опора и адаптивность"),
        blind_spot=blind.get(goal, blind["Другое"]),
        month_theme=month_theme,
        mini_insight=mini_insight,
    )

async def on_startup(bot: Bot):
    await db.connect()
    await db.execute_sql_file("migrations/001_init.sql")
    await db.seed_services()
    await db.seed_admins_from_env(settings.admin_id_list())
    log.info("DB ready")

async def on_shutdown(bot: Bot):
    await db.close()

async def cmd_start(message: Message, bot: Bot):
    uid = message.from_user.id
    if not await db.has_consent(uid):
        await message.answer(texts.CONSENT_TEXT, reply_markup=consent_kb())
        return
    await db.clear_draft(uid)
    await message.answer(texts.MENU_TEXT, reply_markup=menu_kb())

async def consent_cb(call: CallbackQuery):
    uid = call.from_user.id
    await db.add_consent(uid, datetime.utcnow())
    await call.answer("Принято")
    await db.clear_draft(uid)
    await call.message.answer(texts.MENU_TEXT, reply_markup=menu_kb())

# Menu via reply keyboard
async def menu_message(message: Message):
    uid = message.from_user.id
    if not await db.has_consent(uid):
        await message.answer(texts.CONSENT_TEXT, reply_markup=consent_kb())
        return

    txt = (message.text or "").strip()
    if txt == "✨ Астропрофиль (MVP)":
        d = new_draft("ASTRO_BIRTH_DATE")
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASTRO_WELCOME, parse_mode=ParseMode.MARKDOWN)
        await message.answer(texts.ASTRO_DISCLAIMER)
        await message.answer(texts.ASTRO_ASK_BIRTH_DATE)
        return
    if txt == "💳 Платная услуга":
        d = new_draft("PAID_ADDRESS")
        await db.upsert_draft(uid, d)
        await message.answer("Выберите адрес:", reply_markup=address_kb())
        return
    if txt in ("💡 Предложение", "😡 Жалоба"):
        # MVP stub: just ask text and then contact similar to paid, but store in draft under FEEDBACK
        kind = "SUGGESTION" if txt.startswith("💡") else "COMPLAINT"
        d = new_draft("FEEDBACK_TEXT")
        d["kind"] = kind
        await db.upsert_draft(uid, d)
        await message.answer("Напишите текст одним сообщением:")
        return
    if txt == "⬅️ В меню":
        await db.clear_draft(uid)
        await message.answer(texts.MENU_TEXT, reply_markup=menu_kb())
        return

async def nav_cb(call: CallbackQuery):
    uid = call.from_user.id
    d = await db.get_draft(uid) or {}
    target = call.data.split("|", 1)[1]
    if target == "menu":
        await db.clear_draft(uid)
        await call.message.answer(texts.MENU_TEXT, reply_markup=menu_kb())
        await call.answer()
        return
    if target == "cats":
        cats = await db.list_categories()
        d["step"] = "PAID_CATEGORY"
        await db.upsert_draft(uid, d)
        await call.message.edit_text(texts.ASK_CATEGORY, reply_markup=categories_kb(cats))
        await call.answer()
        return
    if target == "services":
        if not d.get("category_id"):
            await call.answer("Нет категории", show_alert=True)
            return
        services = await db.list_services_by_category(int(d["category_id"]))
        d["step"] = "PAID_SERVICE"
        await db.upsert_draft(uid, d)
        await call.message.edit_text(texts.ASK_SERVICE, reply_markup=services_kb([(sid,n,p) for sid,n,p,_,_ in services]))
        await call.answer()
        return
    if target == "dates":
        horizon = settings.BOOKING_HORIZON_DAYS
        dates = date_range(horizon)[:horizon+1]
        d["step"] = "PAID_DATE"
        await db.upsert_draft(uid, d)
        await call.message.edit_text(texts.ask_date(horizon), reply_markup=dates_kb(dates))
        await call.answer()
        return

async def addr_cb(call: CallbackQuery):
    uid = call.from_user.id
    parts = call.data.split("|", 2)
    _, atype, label = parts
    d = await db.get_draft(uid) or new_draft("PAID_ADDRESS")
    d["address_type"] = atype
    if atype == "KNOWN":
        d["address_label"] = label
        d["step"] = "PAID_APT"
        await db.upsert_draft(uid, d)
        await call.message.answer(texts.ASK_APT)
        await call.answer()
        return
    # CUSTOM
    d["address_label"] = ""  # will fill from input
    d["step"] = "PAID_CUSTOM_ADDRESS"
    await db.upsert_draft(uid, d)
    await call.message.answer(texts.ASK_CUSTOM_ADDRESS)
    await call.answer()

async def cat_cb(call: CallbackQuery):
    uid = call.from_user.id
    cid = int(call.data.split("|")[1])
    d = await db.get_draft(uid) or new_draft("PAID_CATEGORY")
    d["category_id"] = cid
    d["step"] = "PAID_SERVICE"
    await db.upsert_draft(uid, d)
    services = await db.list_services_by_category(cid)
    await call.message.edit_text(texts.ASK_SERVICE, reply_markup=services_kb([(sid,n,p) for sid,n,p,_,_ in services]))
    await call.answer()

async def svc_cb(call: CallbackQuery):
    uid = call.from_user.id
    sid = int(call.data.split("|")[1])
    d = await db.get_draft(uid) or {}
    d["service_id"] = sid
    d["step"] = "PAID_DATE"
    await db.upsert_draft(uid, d)
    horizon = settings.BOOKING_HORIZON_DAYS
    dates = date_range(horizon)[:horizon+1]
    await call.message.edit_text(texts.ask_date(horizon), reply_markup=dates_kb(dates))
    await call.answer()

async def date_cb(call: CallbackQuery):
    uid = call.from_user.id
    iso = call.data.split("|")[1]
    d = await db.get_draft(uid) or {}
    d["booking_date"] = iso
    d["step"] = "PAID_SLOTS"
    d.setdefault("slots", [])
    await db.upsert_draft(uid, d)

    slots = generate_slots(settings.WORKDAY_START, settings.WORKDAY_END, settings.SLOT_MIN)
    selected = set(d.get("slots") or [])
    await call.message.edit_text(texts.PICK_SLOTS, reply_markup=slots_kb(slots, selected), parse_mode=ParseMode.MARKDOWN)
    await call.answer()

async def slot_cb(call: CallbackQuery):
    uid = call.from_user.id
    key = call.data.split("|", 1)[1]
    d = await db.get_draft(uid) or {}
    slots_list = list(d.get("slots") or [])
    if key == "DONE":
        if not slots_list:
            await call.answer("Выберите хотя бы один интервал", show_alert=True)
            return
        d["step"] = "PAID_NAME"
        await db.upsert_draft(uid, d)
        await call.message.answer(texts.ASK_NAME)
        await call.answer()
        return

    if key in slots_list:
        slots_list.remove(key)
    else:
        slots_list.append(key)
    d["slots"] = slots_list
    await db.upsert_draft(uid, d)

    slots = generate_slots(settings.WORKDAY_START, settings.WORKDAY_END, settings.SLOT_MIN)
    await call.message.edit_text(texts.PICK_SLOTS, reply_markup=slots_kb(slots, set(slots_list)), parse_mode=ParseMode.MARKDOWN)
    await call.answer()

async def text_router(message: Message, bot: Bot):
    uid = message.from_user.id
    if message.text and message.text.strip() in ("✨ Астропрофиль (MVP)", "💳 Платная услуга", "💡 Предложение", "😡 Жалоба", "⬅️ В меню"):
        return await menu_message(message)

    d = await db.get_draft(uid)
    step = draft_step(d)

    # ADMIN: adjusted price for status change
    if step == "ADMIN_ADJUST_PRICE":
        if not await db.is_admin(uid):
            await db.clear_draft(uid)
            await message.answer("Недостаточно прав.")
            return
        raw = (message.text or "").replace(" ", "").replace("₽", "")
        if not raw.isdigit() or int(raw) <= 0:
            await message.answer("Введите сумму в рублях, например: 1500")
            return
        rid = int(d.get("request_id"))
        pending_status = d.get("pending_status", "IN_PROGRESS")
        price = int(raw)
        await db.set_pending_status_with_price(rid, pending_status, price, uid)
        await db.clear_draft(uid)
        req = await db.get_request(rid)
        if req:
            await bot.send_message(
                req["telegram_user_id"],
                texts.PRICE_CONFIRM_REQUEST.format(id=rid, price=price),
                reply_markup=price_confirm_kb(rid),
                parse_mode=ParseMode.MARKDOWN,
            )
            card = await build_group_card_full(req)
            await bot.edit_message_text(
                card,
                chat_id=req["group_chat_id"] or message.chat.id,
                message_id=req["group_message_id"],
                reply_markup=admin_status_kb(rid),
                parse_mode=ParseMode.MARKDOWN,
            )
        await message.answer(texts.PRICE_PENDING_TO_ADMIN.format(id=rid), reply_markup=menu_kb())
        return

    # ASTRO MVP flow
    if step == "ASTRO_BIRTH_DATE":
        bdate = parse_birth_date(message.text or "")
        if not bdate:
            await message.answer("Неверный формат даты. Пример: 12.03.1991")
            return
        d["birth_date"] = bdate.isoformat()
        d["step"] = "ASTRO_TIME_MODE"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASTRO_ASK_TIME_MODE, reply_markup=astro_time_mode_kb())
        return

    if step == "ASTRO_BIRTH_TIME":
        raw_time = (message.text or "").strip()
        t = None
        if re.fullmatch(r"\d{2}:\d{2}", raw_time):
            try:
                t = parse_hhmm(raw_time)
            except ValueError:
                t = None
        if not t:
            await message.answer("Укажите время в формате ЧЧ:ММ, например 14:25")
            return
        d["birth_time"] = t.strftime("%H:%M")
        d["step"] = "ASTRO_BIRTH_PLACE"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASTRO_ASK_BIRTH_PLACE)
        return

    if step == "ASTRO_BIRTH_PLACE":
        place = (message.text or "").strip()
        if "," not in place or len(place) < 6:
            await message.answer("Укажите в формате «город, страна», например: Казань, Россия")
            return
        d["birth_place"] = place
        d["step"] = "ASTRO_TIMEZONE"
        d.setdefault("timezone", "UTC+3")
        await db.upsert_draft(uid, d)
        await message.answer(f"Я определил {d['timezone']}, верно?", reply_markup=astro_tz_confirm_kb())
        return

    if step == "ASTRO_TIMEZONE":
        tz = parse_timezone(message.text or "")
        if not tz:
            await message.answer("Введите часовой пояс в формате UTC+3 или UTC-5")
            return
        d["timezone"] = tz
        d["step"] = "ASTRO_GOAL"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASTRO_ASK_GOAL, reply_markup=astro_goal_kb())
        return

    # FEEDBACK
    if step == "FEEDBACK_TEXT":
        txt = (message.text or "").strip()
        if len(txt) < 5:
            await message.answer("Текст слишком короткий. Напишите подробнее:")
            return
        d["feedback_text"] = txt
        d["step"] = "FEEDBACK_NAME"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASK_NAME)
        return
    if step == "FEEDBACK_NAME":
        name = (message.text or "").strip()
        if len(name) < 2:
            await message.answer("Имя слишком короткое. Попробуйте ещё раз:")
            return
        d["full_name"] = name
        d["step"] = "FEEDBACK_PHONE"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASK_PHONE, reply_markup=phone_kb())
        return
    if step == "FEEDBACK_PHONE":
        # handle contact in separate handler; here text phone
        ph = normalize_phone(message.text or "")
        if not ph:
            await message.answer("Не похоже на номер телефона. Попробуйте ещё раз или отправьте контакт кнопкой.")
            return
        d["phone"] = ph
        # Post feedback to group
        kind = d.get("kind", "FEEDBACK")
        text = d.get("feedback_text", "")
        name = d.get("full_name", "")
        # ensure profile
        await db.pool.execute(
            """INSERT INTO user_profiles(telegram_user_id, full_name, phone, updated_at)
                 VALUES ($1,$2,$3,NOW())
                 ON CONFLICT (telegram_user_id) DO UPDATE SET full_name=EXCLUDED.full_name, phone=EXCLUDED.phone, updated_at=NOW()""",
            uid, name, ph
        )
        await bot.send_message(
            settings.GROUP_CHAT_ID,
            f"**{('Предложение' if kind=='SUGGESTION' else 'Жалоба')}**\n"
            f"От: {name} ({ph})\n"
            f"UserID: {uid}\n\n"
            f"{text}",
            parse_mode=ParseMode.MARKDOWN
        )
        await db.clear_draft(uid)
        await message.answer("Принято. Спасибо!", reply_markup=menu_kb())
        return

    # PAID flow steps that are text inputs
    if step == "PAID_APT":
        apt = (message.text or "").strip()
        if len(apt) < 1 or len(apt) > 10:
            await message.answer("Введите корректный номер квартиры:")
            return
        d["apartment"] = apt
        d["step"] = "PAID_CATEGORY"
        await db.upsert_draft(uid, d)
        cats = await db.list_categories()
        await message.answer(texts.ASK_CATEGORY, reply_markup=categories_kb(cats))
        return

    if step == "PAID_CUSTOM_ADDRESS":
        addr = (message.text or "").strip()
        if len(addr) < 10:
            await message.answer("Адрес слишком короткий. Укажите улицу, дом, квартиру:")
            return
        d["address_label"] = addr
        d["step"] = "PAID_CATEGORY"
        await db.upsert_draft(uid, d)
        cats = await db.list_categories()
        await message.answer(texts.ASK_CATEGORY, reply_markup=categories_kb(cats))
        return

    if step == "PAID_NAME":
        name = (message.text or "").strip()
        if len(name) < 2:
            await message.answer("Имя слишком короткое. Напишите ещё раз:")
            return
        d["full_name"] = name
        d["step"] = "PAID_PHONE"
        await db.upsert_draft(uid, d)
        await message.answer(texts.ASK_PHONE, reply_markup=phone_kb())
        return

    if step == "PAID_PHONE":
        ph = normalize_phone(message.text or "")
        if not ph:
            await message.answer("Не похоже на номер телефона. Попробуйте ещё раз или отправьте контакт кнопкой.")
            return
        d["phone"] = ph
        await db.upsert_draft(uid, d)
        return await finalize_paid_request(message, bot, uid, d)

    if step == "RATING_COMMENT":
        comment = (message.text or "").strip()
        req_id = int(d.get("rating_request_id"))
        stars = int(d.get("rating_stars"))
        await db.add_rating(req_id, stars, comment if comment else None)
        await db.clear_draft(uid)
        await message.answer(texts.THANKS_RATED, reply_markup=menu_kb())
        # update group card
        req = await db.get_request(req_id)
        if req and req.get("group_chat_id") and req.get("group_message_id"):
            card = await build_group_card_full(req)
            await bot.edit_message_text(
                card,
                chat_id=req["group_chat_id"],
                message_id=req["group_message_id"],
                reply_markup=admin_status_kb(req_id),
                parse_mode=ParseMode.MARKDOWN
            )
        return

async def contact_router(message: Message, bot: Bot):
    uid = message.from_user.id
    d = await db.get_draft(uid)
    step = draft_step(d)
    if not message.contact:
        return
    ph = normalize_phone(message.contact.phone_number or "")
    if not ph:
        await message.answer("Не смог распознать телефон. Напишите номер вручную:")
        return
    if step == "PAID_PHONE":
        d["phone"] = ph
        await db.upsert_draft(uid, d)
        return await finalize_paid_request(message, bot, uid, d)
    if step == "FEEDBACK_PHONE":
        d["phone"] = ph
        await db.upsert_draft(uid, d)
        # handle as in FEEDBACK_PHONE text path:
        kind = d.get("kind", "FEEDBACK")
        text = d.get("feedback_text", "")
        name = d.get("full_name", "")
        await db.pool.execute(
            """INSERT INTO user_profiles(telegram_user_id, full_name, phone, updated_at)
                 VALUES ($1,$2,$3,NOW())
                 ON CONFLICT (telegram_user_id) DO UPDATE SET full_name=EXCLUDED.full_name, phone=EXCLUDED.phone, updated_at=NOW()""",
            uid, name, ph
        )
        await bot.send_message(
            settings.GROUP_CHAT_ID,
            f"**{('Предложение' if kind=='SUGGESTION' else 'Жалоба')}**\n"
            f"От: {name} ({ph})\n"
            f"UserID: {uid}\n\n"
            f"{text}",
            parse_mode=ParseMode.MARKDOWN
        )
        await db.clear_draft(uid)
        await message.answer("Принято. Спасибо!", reply_markup=menu_kb())
        return

async def finalize_paid_request(message: Message, bot: Bot, uid: int, d: dict):
    # Validate draft
    required = ["address_type", "address_label", "service_id", "booking_date", "slots", "full_name", "phone"]
    for k in required:
        if not d.get(k):
            await message.answer("Не хватает данных для создания заявки. Начните заново из меню.", reply_markup=menu_kb())
            await db.clear_draft(uid)
            return

    # Parse slots
    slots_pairs = []
    for s in d["slots"]:
        a,b2 = s.split("-", 1)
        slots_pairs.append((parse_hhmm(a), parse_hhmm(b2)))

    rid = await db.create_request(
        telegram_user_id=uid,
        address_type=d["address_type"],
        address_label=d["address_label"] if d["address_type"] == "CUSTOM" else d["address_label"],
        apartment=d.get("apartment"),
        service_id=int(d["service_id"]),
        booking_date=date.fromisoformat(d["booking_date"]),
        slots=slots_pairs,
        full_name=d["full_name"],
        phone=d["phone"]
    )

    await db.clear_draft(uid)

    # Post to group
    req = await db.get_request(rid)
    card = await build_group_card_full(req)
    msg = await bot.send_message(
        settings.GROUP_CHAT_ID,
        card,
        reply_markup=admin_status_kb(rid),
        parse_mode=ParseMode.MARKDOWN
    )
    await db.set_request_group_message(rid, settings.GROUP_CHAT_ID, msg.message_id)

    await message.answer(texts.CONFIRM_CREATED.format(id=rid), reply_markup=menu_kb())

async def status_cb(call: CallbackQuery, bot: Bot):
    parts = call.data.split("|")
    _, rid_s, status = parts
    rid = int(rid_s)

    if not await db.is_admin(call.from_user.id):
        await call.answer("Недостаточно прав", show_alert=True)
        return

    req = await db.get_request(rid)
    if not req:
        await call.answer("Заявка не найдена", show_alert=True)
        return

    if status == "IN_PROGRESS":
        d = new_draft("ADMIN_ADJUST_PRICE")
        d["request_id"] = rid
        d["pending_status"] = status
        await db.upsert_draft(call.from_user.id, d)
        await call.message.answer(
            f"Введите скорректированную сумму для заявки №{rid} (в рублях):"
        )
        await call.answer("Ожидаю сумму")
        return

    await db.update_status(rid, status, changed_by=call.from_user.id)
    req = await db.get_request(rid)

    card = await build_group_card_full(req)
    try:
        await bot.edit_message_text(
            card,
            chat_id=req["group_chat_id"] or call.message.chat.id,
            message_id=req["group_message_id"] or call.message.message_id,
            reply_markup=admin_status_kb(rid),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        log.warning("Failed to edit group message: %s", e)

    await bot.send_message(
        req["telegram_user_id"],
        texts.STATUS_CHANGED.format(id=rid, status=STATUS_LABEL.get(status, status)),
        parse_mode=ParseMode.MARKDOWN,
    )

    if status == "DONE":
        await bot.send_message(
            req["telegram_user_id"],
            texts.RATE_TEXT.format(id=rid),
            reply_markup=rating_kb(rid),
        )

    await call.answer("Ок")


async def price_cb(call: CallbackQuery, bot: Bot):
    _, rid_s, decision = call.data.split("|")
    rid = int(rid_s)

    req = await db.get_request(rid)
    if not req or req["telegram_user_id"] != call.from_user.id:
        await call.answer("Недоступно", show_alert=True)
        return

    if not req.get("pending_status") or req.get("pending_status") != "IN_PROGRESS":
        await call.answer("Запрос уже обработан", show_alert=True)
        return

    if decision == "confirm":
        await db.confirm_pending_status(rid, changed_by=call.from_user.id)
        req = await db.get_request(rid)
        await call.message.answer(texts.PRICE_CONFIRMED_TO_CLIENT.format(id=rid), parse_mode=ParseMode.MARKDOWN)
        await bot.send_message(
            req["group_chat_id"],
            f"Клиент подтвердил сумму {req['price_snapshot_rub']} ₽ по заявке №{rid}.",
        )
        card = await build_group_card_full(req)
        await bot.edit_message_text(
            card,
            chat_id=req["group_chat_id"],
            message_id=req["group_message_id"],
            reply_markup=admin_status_kb(rid),
            parse_mode=ParseMode.MARKDOWN,
        )
        await call.answer("Подтверждено")
        return

    admin_id = req.get("pending_status_requested_by")
    await db.clear_pending_status(rid)
    req = await db.get_request(rid)
    await call.message.answer(texts.PRICE_REJECTED_TO_CLIENT.format(id=rid))
    if admin_id:
        await bot.send_message(admin_id, texts.PRICE_REJECTED_TO_ADMIN.format(id=rid))
    card = await build_group_card_full(req)
    await bot.edit_message_text(
        card,
        chat_id=req["group_chat_id"],
        message_id=req["group_message_id"],
        reply_markup=admin_status_kb(rid),
        parse_mode=ParseMode.MARKDOWN,
    )
    await call.answer("Отклонено")


async def rate_cb(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    _, rid_s, stars_s = call.data.split("|")
    rid = int(rid_s)
    stars = int(stars_s)

    req = await db.get_request(rid)
    if not req or req["telegram_user_id"] != uid:
        await call.answer("Недоступно", show_alert=True)
        return
    if not req.get("awaiting_rating"):
        await call.answer("Оценка уже принята или не требуется", show_alert=True)
        return

    d = new_draft("RATING_COMMENT")
    d["rating_request_id"] = rid
    d["rating_stars"] = stars
    await db.upsert_draft(uid, d)

    await call.message.answer("Спасибо! Теперь оставьте комментарий (или напишите «-», если без комментария):")
    await call.answer()



async def astro_time_cb(call: CallbackQuery):
    uid = call.from_user.id
    mode = call.data.split("|", 1)[1]
    d = await db.get_draft(uid) or new_draft("ASTRO_TIME_MODE")
    d["birth_time_mode"] = mode
    if mode == "UNKNOWN":
        d["birth_time"] = "unknown"
        d["step"] = "ASTRO_BIRTH_PLACE"
        await db.upsert_draft(uid, d)
        await call.message.answer(texts.ASTRO_PRECISION_UNKNOWN)
        await call.message.answer(texts.ASTRO_ASK_BIRTH_PLACE)
        await call.answer()
        return
    d["step"] = "ASTRO_BIRTH_TIME"
    await db.upsert_draft(uid, d)
    await call.message.answer(texts.ASTRO_PRECISION_EXACT if mode == "EXACT" else texts.ASTRO_PRECISION_APPROX)
    await call.message.answer(texts.ASTRO_ASK_BIRTH_TIME if mode == "EXACT" else texts.ASTRO_ASK_BIRTH_TIME_APPROX)
    await call.answer()


async def astro_tz_cb(call: CallbackQuery):
    uid = call.from_user.id
    decision = call.data.split("|", 1)[1]
    d = await db.get_draft(uid) or {}
    if decision == "yes":
        d["step"] = "ASTRO_GOAL"
        await db.upsert_draft(uid, d)
        await call.message.answer(texts.ASTRO_ASK_GOAL, reply_markup=astro_goal_kb())
        await call.answer("Принято")
        return
    d["step"] = "ASTRO_TIMEZONE"
    await db.upsert_draft(uid, d)
    await call.message.answer(texts.ASTRO_ASK_TZ)
    await call.answer()


async def astro_goal_cb(call: CallbackQuery):
    uid = call.from_user.id
    goal = call.data.split("|", 1)[1]
    d = await db.get_draft(uid) or {}
    d["goal"] = goal
    d["step"] = "ASTRO_CONFIRM"
    await db.upsert_draft(uid, d)
    time_mode = d.get("birth_time_mode", "UNKNOWN")
    if time_mode == "UNKNOWN":
        time_label = "не знаю"
    elif time_mode == "APPROX":
        time_label = f"{d.get('birth_time', '—')} (примерно)"
    else:
        time_label = d.get("birth_time", "—")
    await call.message.answer(
        texts.ASTRO_CONFIRM.format(
            birth_date=date.fromisoformat(d['birth_date']).strftime('%d.%m.%Y'),
            birth_time_label=time_label,
            birth_place=d.get('birth_place', '—'),
            timezone=d.get('timezone', 'UTC+3'),
            goal=goal,
        )
    )
    await call.message.answer("Подтвердите данные:", reply_markup=astro_confirm_kb())
    await call.answer()




async def astro_confirm_cb(call: CallbackQuery):
    uid = call.from_user.id
    decision = call.data.split("|", 1)[1]
    d = await db.get_draft(uid) or {}
    if decision == "edit":
        d["step"] = "ASTRO_BIRTH_DATE"
        await db.upsert_draft(uid, d)
        await call.message.answer("Хорошо, начнем заново.")
        await call.message.answer(texts.ASTRO_ASK_BIRTH_DATE)
        await call.answer()
        return

    if not d.get("birth_date") or not d.get("birth_place"):
        await call.answer("Данные профиля не найдены. Начните заново.", show_alert=True)
        return

    passport = build_astro_passport(d)
    await call.message.answer(passport, parse_mode=ParseMode.MARKDOWN)
    await call.message.answer(texts.ASTRO_PROFILE_SAVED)
    await call.message.answer("Выберите расклад:", reply_markup=astro_packages_kb())
    await db.clear_draft(uid)
    await call.answer("Готово")

async def astro_pack_cb(call: CallbackQuery):
    await call.answer("Пакет сохранен. Скоро откроем оплату в боте.")

async def router_minus_comment(message: Message, bot: Bot):
    # helper: allow '-' as skip
    uid = message.from_user.id
    d = await db.get_draft(uid)
    if draft_step(d) == "RATING_COMMENT":
        if (message.text or "").strip() == "-":
            req_id = int(d.get("rating_request_id"))
            stars = int(d.get("rating_stars"))
            await db.add_rating(req_id, stars, None)
            await db.clear_draft(uid)
            await message.answer(texts.THANKS_RATED, reply_markup=menu_kb())
            req = await db.get_request(req_id)
            if req and req.get("group_chat_id") and req.get("group_message_id"):
                card = await build_group_card_full(req)
                await bot.edit_message_text(
                    card,
                    chat_id=req["group_chat_id"],
                    message_id=req["group_message_id"],
                    reply_markup=admin_status_kb(req_id),
                    parse_mode=ParseMode.MARKDOWN
                )
            return True
    return False

async def main():
    bot = Bot(
        settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.message.register(cmd_start, F.text == "/start")
    dp.callback_query.register(consent_cb, F.data == "consent|yes")

    dp.callback_query.register(nav_cb, F.data.startswith("nav|"))
    dp.callback_query.register(addr_cb, F.data.startswith("addr|"))
    dp.callback_query.register(cat_cb, F.data.startswith("cat|"))
    dp.callback_query.register(svc_cb, F.data.startswith("svc|"))
    dp.callback_query.register(date_cb, F.data.startswith("date|"))
    dp.callback_query.register(slot_cb, F.data.startswith("slot|"))
    dp.callback_query.register(status_cb, F.data.startswith("status|"))
    dp.callback_query.register(rate_cb, F.data.startswith("rate|"))
    dp.callback_query.register(price_cb, F.data.startswith("price|"))
    dp.callback_query.register(astro_time_cb, F.data.startswith("astro_time|"))
    dp.callback_query.register(astro_tz_cb, F.data.startswith("astro_tz|"))
    dp.callback_query.register(astro_goal_cb, F.data.startswith("astro_goal|"))
    dp.callback_query.register(astro_confirm_cb, F.data.startswith("astro_confirm|"))
    dp.callback_query.register(astro_pack_cb, F.data.startswith("astro_pack|"))

    dp.message.register(contact_router, F.contact)
    dp.message.register(text_router)

    log.info("Bot starting")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
