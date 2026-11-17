from __future__ import annotations

import asyncio
import html
import logging

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .algorithm import DrawImpossibleError
from .config import Settings
from .db import Database
from .keyboards import game_panel, home
from .media import MediaLibrary
from .states import CreateGame, JoinByCode, Registration
from .texts import DRAW_DONE, GAME_INTRO, RESULT, WELCOME

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
db: Database
settings: Settings
media: MediaLibrary


async def answer_event(message: Message, event: str, text: str, **kwargs) -> None:
    picture = media.pick(event)
    if picture:
        await message.answer_photo(picture, caption=text, **kwargs)
    else:
        await message.answer(text, **kwargs)


def game_text(game, count: int) -> str:
    status = "регистрация открыта" if game["status"] == "open" else "жеребьёвка завершена"
    budget = html.escape(game["budget"] or "не указан")
    date = html.escape(game["exchange_date"] or "договоритесь сами")
    return (
        f"🎄 <b>{html.escape(game['title'])}</b>\n\n{GAME_INTRO}\n\n"
        f"🔑 Код: <code>{game['code']}</code>\n💰 Бюджет: {budget}\n"
        f"📅 Обмен подарками: {date}\n👥 Участников: {count}\n📍 Статус: {status}"
    )


async def show_game(target: Message, game_id: int, user_id: int) -> None:
    game = await db.get_game(game_id)
    if not game:
        await target.answer("Игра не найдена.", reply_markup=home())
        return
    people = await db.participants(game_id)
    joined = any(row["user_id"] == user_id for row in people)
    await target.answer(
        game_text(game, len(people)),
        reply_markup=game_panel(game, creator=game["creator_id"] == user_id, joined=joined, username=settings.bot_username),
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("join_"):
        game = await db.get_game_by_code(parts[1][5:])
        if game:
            await show_game(message, game["id"], message.from_user.id)
            return
    await answer_event(message, "welcome", WELCOME, reply_markup=home())


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "<b>Как это работает</b>\n\n1. Организатор создаёт игру и делится ссылкой.\n"
        "2. Каждый вводит имя, пожелание и по желанию фото.\n"
        "3. Организатор запускает жеребьёвку.\n4. Результат приходит каждому лично.\n\n"
        "Команды: /start — меню, /cancel — отменить ввод."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=home())


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(WELCOME, reply_markup=home())


@router.callback_query(F.data == "create")
async def create_begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateGame.title)
    await callback.answer()
    await callback.message.answer("Как назовём игру? Например: <b>Архыз 2027</b>")


@router.message(CreateGame.title)
async def create_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 2 <= len(title) <= 80:
        await message.answer("Название должно быть от 2 до 80 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(CreateGame.budget)
    await message.answer("Какой бюджет на подарок? Напиши, например, <b>до 5 000 ₽</b>, или отправь «-».")


@router.message(CreateGame.budget)
async def create_budget(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    await state.update_data(budget=None if value == "-" else value[:100])
    await state.set_state(CreateGame.exchange_date)
    await message.answer("Когда обмениваемся подарками? Например, <b>1 января на Архызе</b>, или «-».")


@router.message(CreateGame.exchange_date)
async def create_date(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    game = await db.create_game(message.from_user.id, data["title"], data["budget"], None if value == "-" else value[:120])
    await state.clear()
    await answer_event(message, "created", "✨ <b>Игра создана!</b> Организатор может участвовать наравне со всеми — просто нажми кнопку регистрации ниже.")
    await show_game(message, game["id"], message.from_user.id)


@router.callback_query(F.data == "joincode")
async def join_code_begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(JoinByCode.code)
    await callback.answer()
    await callback.message.answer("Пришли шестизначный код игры:")


@router.message(JoinByCode.code)
async def join_code_finish(message: Message, state: FSMContext) -> None:
    game = await db.get_game_by_code(message.text or "")
    if not game:
        await message.answer("Такого кода нет. Проверь символы и попробуй ещё раз или нажми /cancel.")
        return
    await state.clear()
    await show_game(message, game["id"], message.from_user.id)


@router.callback_query(F.data == "mygames")
async def my_games(callback: CallbackQuery) -> None:
    games = await db.user_games(callback.from_user.id)
    await callback.answer()
    if not games:
        await callback.message.answer("У тебя пока нет игр.", reply_markup=home())
        return
    builder = InlineKeyboardBuilder()
    for game in games:
        icon = "🟢" if game["status"] == "open" else "🎁"
        builder.button(text=f"{icon} {game['title']}", callback_data=f"game:{game['id']}")
    builder.button(text="⌂ Главное меню", callback_data="home")
    builder.adjust(1)
    await callback.message.answer("🎄 <b>Мои игры</b>", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("game:"))
async def open_game(callback: CallbackQuery) -> None:
    await callback.answer()
    await show_game(callback.message, int(callback.data.split(":")[1]), callback.from_user.id)


@router.callback_query(F.data.startswith("join:"))
async def join_begin(callback: CallbackQuery, state: FSMContext) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game or game["status"] != "open":
        await callback.answer("Регистрация уже закрыта", show_alert=True)
        return
    if await db.participant(game_id, callback.from_user.id):
        await callback.answer("Ты уже участвуешь", show_alert=True)
        return
    await state.set_state(Registration.name)
    await state.update_data(game_id=game_id)
    await callback.answer()
    await callback.message.answer("Как тебя записать? Отправь имя и фамилию:")


@router.message(Registration.name)
async def registration_name(message: Message, state: FSMContext) -> None:
    name = " ".join((message.text or "").split())
    if not 2 <= len(name) <= 80:
        await message.answer("Имя должно быть от 2 до 80 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Registration.wish)
    await message.answer("Что ты хочешь получить? Напиши пожелание или отправь «-», если сюрприз важнее.")


@router.message(Registration.wish)
async def registration_wish(message: Message, state: FSMContext) -> None:
    wish = (message.text or "").strip()
    await state.update_data(wish=None if wish == "-" else wish[:1000])
    await state.set_state(Registration.photo)
    await message.answer("Пришли свою смешную фотографию или отправь «-». Она будет видна только твоему Тайному Санте.")


@router.message(Registration.photo)
async def registration_photo(message: Message, state: FSMContext) -> None:
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif (message.text or "").strip() == "-":
        photo_id = None
    else:
        await message.answer("Нужна фотография или символ «-».")
        return
    data = await state.get_data()
    try:
        await db.add_participant(data["game_id"], message.from_user.id, data["name"], data["wish"], photo_id)
    except aiosqlite.IntegrityError:
        await state.clear()
        await message.answer("Такой участник уже зарегистрирован в этой игре. Имена сравниваются без учёта регистра и ё/е.")
        return
    await state.clear()
    await answer_event(message, "joined", "✅ <b>Ты в игре!</b> Теперь можно спокойно готовить праздничное настроение.")
    await show_game(message, data["game_id"], message.from_user.id)


@router.callback_query(F.data.startswith("parts:"))
async def show_participants(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return
    people = await db.participants(game_id)
    names = "\n".join(f"{i}. {html.escape(p['name'])}" for i, p in enumerate(people, 1)) or "Пока никого."
    await callback.answer()
    await callback.message.answer(f"👥 <b>Зарегистрированные участники ({len(people)}):</b>\n\n{names}")


@router.callback_query(F.data.startswith("leave:"))
async def leave_game(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    removed = await db.leave(game_id, callback.from_user.id)
    await callback.answer("Ты вышел из игры" if removed else "После жеребьёвки выйти нельзя", show_alert=True)
    if removed:
        await show_game(callback.message, game_id, callback.from_user.id)


@router.callback_query(F.data.startswith("excl:"))
async def exclusions_panel(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game or game["creator_id"] != callback.from_user.id or game["status"] != "open":
        await callback.answer("Недоступно", show_alert=True)
        return
    people = await db.participants(game_id)
    pairs = await db.exclusions(game_id)
    current = "\n".join(f"• {html.escape(x['name_a'])} ↔ {html.escape(x['name_b'])}" for x in pairs) or "пока нет"
    builder = InlineKeyboardBuilder()
    for person in people:
        builder.button(text=person["name"], callback_data=f"xa:{game_id}:{person['id']}")
    builder.adjust(1)
    await callback.answer()
    await callback.message.answer(
        f"🚫 <b>Исключения</b>\nЭти люди не смогут вытянуть друг друга.\n\nСейчас: {current}\n\nВыбери первого человека:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("xa:"))
async def exclusion_first(callback: CallbackQuery) -> None:
    _, gid, first = callback.data.split(":")
    people = await db.participants(int(gid))
    builder = InlineKeyboardBuilder()
    for person in people:
        if person["id"] != int(first):
            builder.button(text=person["name"], callback_data=f"xb:{gid}:{first}:{person['id']}")
    builder.adjust(1)
    await callback.answer()
    await callback.message.answer("Теперь выбери второго человека:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("xb:"))
async def exclusion_second(callback: CallbackQuery) -> None:
    _, gid, first, second = callback.data.split(":")
    game = await db.get_game(int(gid))
    if not game or game["creator_id"] != callback.from_user.id:
        await callback.answer("Только организатор", show_alert=True)
        return
    await db.add_exclusion(int(gid), int(first), int(second))
    await callback.answer("Исключение добавлено", show_alert=True)


@router.callback_query(F.data.startswith("drawask:"))
async def draw_ask(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game or game["creator_id"] != callback.from_user.id:
        await callback.answer("Только организатор может начать игру", show_alert=True)
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Да, перемешать всех", callback_data=f"draw:{game_id}", style="success")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"game:{game_id}")],
    ])
    await callback.answer()
    await callback.message.answer("После старта нельзя добавлять и удалять участников. Начинаем?", reply_markup=markup)


async def send_result(bot: Bot, user_id: int, row) -> None:
    text = RESULT.format(name=html.escape(row["name"]), wish=html.escape(row["wish"] or "нет — придумывай сам 😈"))
    if row["photo_file_id"]:
        await bot.send_photo(user_id, row["photo_file_id"], caption=text)
    else:
        await bot.send_message(user_id, text)


@router.callback_query(F.data.startswith("draw:"))
async def draw_game(callback: CallbackQuery, bot: Bot) -> None:
    game_id = int(callback.data.split(":")[1])
    game = await db.get_game(game_id)
    if not game or game["creator_id"] != callback.from_user.id:
        await callback.answer("Только организатор", show_alert=True)
        return
    await callback.answer("Перемешиваю…")
    try:
        rows = await db.draw(game_id)
    except (ValueError, DrawImpossibleError) as exc:
        await callback.message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    failed = 0
    for row in rows:
        try:
            await send_result(bot, row["giver_user_id"], row)
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
    suffix = f"\n\n⚠️ Не удалось доставить: {failed}. Эти участники смогут нажать «Получить своё имя»." if failed else ""
    await answer_event(callback.message, "drawn", DRAW_DONE + suffix)
    await show_game(callback.message, game_id, callback.from_user.id)


@router.callback_query(F.data.startswith("result:"))
async def get_result(callback: CallbackQuery, bot: Bot) -> None:
    game_id = int(callback.data.split(":")[1])
    row = await db.result(game_id, callback.from_user.id)
    if not row:
        await callback.answer("Результат пока недоступен", show_alert=True)
        return
    await callback.answer("Отправил лично 🤫", show_alert=True)
    await send_result(bot, callback.from_user.id, row)


@router.callback_query(F.data.startswith("delask:"))
async def delete_ask(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить навсегда", callback_data=f"delete:{game_id}", style="danger")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"game:{game_id}")],
    ])
    await callback.answer()
    await callback.message.answer("Точно удалить игру и все данные? Это нельзя отменить.", reply_markup=markup)


@router.callback_query(F.data.startswith("delete:"))
async def delete_game(callback: CallbackQuery) -> None:
    game_id = int(callback.data.split(":")[1])
    deleted = await db.delete_game(game_id, callback.from_user.id)
    await callback.answer("Игра удалена" if deleted else "Удалить может только организатор", show_alert=True)
    if deleted:
        await callback.message.answer(WELCOME, reply_markup=home())


async def main() -> None:
    global db, settings, media
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    db = Database(settings.database_path)
    media = MediaLibrary(settings.assets_dir)
    await db.init()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Как играть"),
        BotCommand(command="cancel", description="Отменить текущий ввод"),
    ])
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

