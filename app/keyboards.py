from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from datetime import date
from typing import List, Tuple
from .utils import format_date_btn

def consent_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, согласен", callback_data="consent|yes")
    return b.as_markup()

def menu_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(
        KeyboardButton(text="💳 Платная услуга"),
        KeyboardButton(text="💡 Предложение"),
        KeyboardButton(text="😡 Жалоба"),
    )
    b.adjust(1)
    return b.as_markup(resize_keyboard=True)

def address_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Привольная 21", callback_data="addr|KNOWN|Привольная 21")
    b.button(text="Привольная 23", callback_data="addr|KNOWN|Привольная 23")
    b.button(text="Привольная 25", callback_data="addr|KNOWN|Привольная 25")
    b.button(text="Другой адрес", callback_data="addr|CUSTOM|Другой адрес")
    b.adjust(2,2)
    return b.as_markup()

def categories_kb(categories: List[tuple[int,str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cid, name in categories:
        b.button(text=name, callback_data=f"cat|{cid}")
    b.button(text="⬅️ Назад", callback_data="nav|menu")
    b.adjust(1)
    return b.as_markup()

def services_kb(services: List[tuple[int,str,int]]) -> InlineKeyboardMarkup:
    # (id, name, price)
    b = InlineKeyboardBuilder()
    for sid, name, price in services:
        b.button(text=f"{name} — {price} ₽", callback_data=f"svc|{sid}")
    b.button(text="⬅️ Назад", callback_data="nav|cats")
    b.adjust(1)
    return b.as_markup()

def dates_kb(dates: List[date]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in dates:
        b.button(text=format_date_btn(d), callback_data=f"date|{d.isoformat()}")
    b.button(text="⬅️ Назад", callback_data="nav|services")
    b.adjust(2)
    return b.as_markup()

def slots_kb(slots: List[Tuple[str,str]], selected: set[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for a,b2 in slots:
        key = f"{a}-{b2}"
        prefix = "✅ " if key in selected else ""
        b.button(text=f"{prefix}{a}–{b2}", callback_data=f"slot|{key}")
    b.button(text="✅ Готово", callback_data="slot|DONE")
    b.button(text="⬅️ Назад", callback_data="nav|dates")
    b.adjust(2)
    return b.as_markup()

def phone_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="📱 Отправить контакт", request_contact=True))
    b.add(KeyboardButton(text="⬅️ В меню"))
    b.adjust(1)
    return b.as_markup(resize_keyboard=True)

def rating_kb(request_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(1,6):
        b.button(text=f"⭐ {i}", callback_data=f"rate|{request_id}|{i}")
    b.adjust(5)
    return b.as_markup()

def admin_status_kb(request_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🛠 В работе", callback_data=f"status|{request_id}|IN_PROGRESS")
    b.button(text="✅ Выполнена", callback_data=f"status|{request_id}|DONE")
    b.button(text="📦 Архив", callback_data=f"status|{request_id}|ARCHIVED")
    b.adjust(3)
    return b.as_markup()


def price_confirm_kb(request_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data=f"price|{request_id}|confirm")
    b.button(text="❌ Не согласен", callback_data=f"price|{request_id}|reject")
    b.adjust(2)
    return b.as_markup()
