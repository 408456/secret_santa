from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать игру", callback_data="create", style="primary")],
        [InlineKeyboardButton(text="🎟 Присоединиться к игре", callback_data="joincode", style="success")],
        [InlineKeyboardButton(text="🎄 Мои игры", callback_data="mygames")],
    ])


def game_panel(game, *, creator: bool, joined: bool, username: str) -> InlineKeyboardMarkup:
    gid = game["id"]
    builder = InlineKeyboardBuilder()
    if game["status"] == "open":
        if not joined:
            builder.button(text="🎁 Присоединиться к игре", callback_data=f"join:{gid}", style="success")
        else:
            builder.button(text="🚪 Выйти из игры", callback_data=f"leave:{gid}", style="danger")
        builder.button(text="👥 Посмотреть участников", callback_data=f"parts:{gid}")
        if creator:
            builder.button(text="🚫 Настроить исключения", callback_data=f"excl:{gid}")
            builder.button(text="🎲 Начать игру", callback_data=f"drawask:{gid}", style="primary")
    else:
        if joined:
            builder.button(text="🔐 Получить своё имя", callback_data=f"result:{gid}", style="success")
        builder.button(text="👥 Участники", callback_data=f"parts:{gid}")
    invite = f"https://t.me/{username}?start=join_{game['code']}"
    builder.button(text="🔗 Поделиться приглашением", url=f"https://t.me/share/url?url={invite}")
    builder.button(text="📋 Скопировать код", copy_text=CopyTextButton(text=game["code"]))
    if creator:
        builder.button(text="🗑 Удалить игру", callback_data=f"delask:{gid}", style="danger")
    builder.button(text="⌂ Главное меню", callback_data="home")
    builder.adjust(1)
    return builder.as_markup()

