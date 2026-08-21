import asyncio
import logging
import os
import random
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from questions import DARES, TRUTHS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("truth_or_dare")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задана переменная окружения BOT_TOKEN. "
        "Добавьте её в Railway (Variables) или в файл .env локально."
    )

router = Router()

# Список игроков по каждому чату: chat_id -> {user_id: имя}
# Хранится в памяти: при перезапуске/передеплое бота список сбрасывается.
players: dict[int, dict[int, str]] = defaultdict(dict)

WELCOME = (
    "🎲 <b>Правда или Действие</b>\n\n"
    "Бот сам выбирает <b>двух случайных игроков</b>: один спрашивает, другой "
    "отвечает или выполняет задание.\n\n"
    "<b>Как играть:</b>\n"
    "1) Каждый жмёт «✅ Участвую» (или /join)\n"
    "2) Кто-нибудь жмёт «🎲 Начать раунд»\n"
    "3) Бот вытягивает случайную пару и вопрос/задание\n\n"
    "<b>Команды:</b>\n"
    "/join — войти в игру\n"
    "/leave — выйти\n"
    "/players — кто играет\n"
    "/spin — начать раунд\n"
    "/help — помощь"
)


# ---------- клавиатуры ----------

def lobby_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Участвую", callback_data="join"),
                InlineKeyboardButton(text="🚪 Выйти", callback_data="leave"),
            ],
            [InlineKeyboardButton(text="🎲 Начать раунд", callback_data="round:random")],
            [InlineKeyboardButton(text="👥 Кто играет", callback_data="list")],
        ]
    )


def round_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Следующий раунд", callback_data="round:random")],
            [
                InlineKeyboardButton(text="🗣 Правда", callback_data="round:truth"),
                InlineKeyboardButton(text="🔥 Действие", callback_data="round:dare"),
            ],
            [
                InlineKeyboardButton(text="✅ Участвую", callback_data="join"),
                InlineKeyboardButton(text="👥 Кто играет", callback_data="list"),
            ],
        ]
    )


# ---------- вспомогательное ----------

def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def players_text(chat_id: int) -> str:
    people = players[chat_id]
    if not people:
        return "Пока никто не присоединился. Жмите «✅ Участвую» или /join."
    lines = [
        f"{i}. {mention(uid, name)}"
        for i, (uid, name) in enumerate(people.items(), 1)
    ]
    return f"👥 <b>Игроки ({len(people)}):</b>\n" + "\n".join(lines)


def build_round_text(people: dict[int, str], kind: str) -> tuple[str, str]:
    """Чистая логика раунда. Возвращает (текст, тип). kind: random|truth|dare."""
    asker_id, answerer_id = random.sample(list(people.keys()), 2)
    asker = mention(asker_id, people[asker_id])
    answerer = mention(answerer_id, people[answerer_id])

    if kind == "random":
        kind = random.choice(("truth", "dare"))

    if kind == "truth":
        label, item, verb = "🗣 <b>Правда</b>", random.choice(TRUTHS), "задаёт вопрос"
    else:
        label, item, verb = "🔥 <b>Действие</b>", random.choice(DARES), "даёт задание"

    text = (
        "🎲 <b>Новый раунд!</b>\n\n"
        f"🗣 Спрашивает: {asker}\n"
        f"🙋 Отвечает/выполняет: {answerer}\n\n"
        f"{asker} {verb} — {label} для {answerer}:\n\n{item}"
    )
    return text, kind


async def do_round(message: Message, chat_id: int, kind: str) -> None:
    people = players[chat_id]
    if len(people) < 2:
        await message.answer(
            "Нужно минимум <b>2 игрока</b>. Жмите «✅ Участвую» или /join.",
            reply_markup=lobby_kb(),
        )
        return
    text, _ = build_round_text(people, kind)
    await message.answer(text, reply_markup=round_kb())


# ---------- команды ----------

@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=lobby_kb())


@router.message(Command("join"))
async def cmd_join(message: Message) -> None:
    user = message.from_user
    players[message.chat.id][user.id] = user.full_name or "Игрок"
    await message.answer(
        f"✅ {mention(user.id, user.full_name)} в игре!\n\n"
        + players_text(message.chat.id),
        reply_markup=lobby_kb(),
    )


@router.message(Command("leave"))
async def cmd_leave(message: Message) -> None:
    players[message.chat.id].pop(message.from_user.id, None)
    await message.answer(
        "🚪 Вы вышли из игры.\n\n" + players_text(message.chat.id),
        reply_markup=lobby_kb(),
    )


@router.message(Command("players"))
async def cmd_players(message: Message) -> None:
    await message.answer(players_text(message.chat.id), reply_markup=lobby_kb())


@router.message(Command("spin"))
async def cmd_spin(message: Message) -> None:
    await do_round(message, message.chat.id, "random")


# ---------- кнопки ----------

@router.callback_query(F.data == "join")
async def cb_join(callback: CallbackQuery) -> None:
    user = callback.from_user
    chat_id = callback.message.chat.id
    if user.id in players[chat_id]:
        await callback.answer("Вы уже в игре 🙂")
        return
    players[chat_id][user.id] = user.full_name or "Игрок"
    await callback.answer("Вы в игре! ✅")
    await callback.message.answer(players_text(chat_id), reply_markup=lobby_kb())


@router.callback_query(F.data == "leave")
async def cb_leave(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    if players[chat_id].pop(callback.from_user.id, None) is None:
        await callback.answer("Вас и так не было в игре 🙂")
        return
    await callback.answer("Вы вышли 🚪")
    await callback.message.answer(players_text(chat_id), reply_markup=lobby_kb())


@router.callback_query(F.data == "list")
async def cb_list(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        players_text(callback.message.chat.id), reply_markup=lobby_kb()
    )


@router.callback_query(F.data.startswith("round:"))
async def cb_round(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]  # random | truth | dare
    await callback.answer()
    await do_round(callback.message, callback.message.chat.id, kind)


# ---------- запуск ----------

async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Бот запущен, начинаю polling…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
