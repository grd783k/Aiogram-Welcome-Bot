import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from database import get_all_users, init_db, register_user, user_count

# ── Config ────────────────────────────────────────────────────────────────────

# Remove all whitespace in case the token was pasted with extra characters
BOT_TOKEN = "".join((os.environ.get("BOT_TOKEN") or "").split())

# Optional: set ADMIN_ID secret to your Telegram user_id to protect /broadcast and /stats
ADMIN_ID_RAW = "".join((os.environ.get("ADMIN_ID") or "").split())
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

DELETE_AFTER = 3600  # seconds (1 hour)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ── Auto-delete helper ────────────────────────────────────────────────────────

async def delete_after(message: Message, delay: int = DELETE_AFTER) -> None:
    """Wait `delay` seconds then silently delete `message`."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    except Exception as e:
        logger.debug("Could not delete message %s: %s", message.message_id, e)


def schedule_deletion(message: Message) -> None:
    """Fire-and-forget: schedule a message for deletion after DELETE_AFTER seconds."""
    asyncio.create_task(delete_after(message))


# ── Admin guard ───────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    """Return True if ADMIN_ID is not set (open) or if user_id matches."""
    return ADMIN_ID is None or user_id == ADMIN_ID


# ── Keyboards ────────────────────────────────────────────────────────────────

def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📲 Ouvrir le menu",
                    web_app=WebAppInfo(url="https://www.guardiola66.com/login"),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📞 Contact",
                    url="https://wa.me/212625902052",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕘 horraire",
                    callback_data="horraire",
                )
            ],
        ]
    )


# ── Handlers ─────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    user = message.from_user

    # ── Register user (no duplicate if /start sent again) ──
    if user:
        is_new = register_user(
            user_id=user.id,
            chat_id=message.chat.id,
            first_name=user.first_name or "",
            username=user.username,
        )
        if is_new:
            logger.info("New user registered: id=%s name=%s", user.id, user.first_name)

    # ── Build welcome text ──
    name = (user.first_name if user and user.first_name else None) or \
           (user.username if user and user.username else None)
    text = f"👋 Bienvenue sur la mini App , {name} !" if name \
           else "👋 Bienvenue sur la mini App !"

    keyboard = start_keyboard()
    photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")

    if not os.path.exists(photo_path):
        logger.warning("welcome.jpg not found — sending text only.")
        sent = await message.answer(text=text, reply_markup=keyboard)
    else:
        photo = FSInputFile(photo_path)
        sent = await message.answer_photo(photo=photo, caption=text, reply_markup=keyboard)

    schedule_deletion(sent)


@dp.message(Command("contact"))
async def contact_handler(message: types.Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 WhatsApp",
                    url="https://wa.me/212625902052",
                )
            ]
        ]
    )
    sent = await message.answer(text="📱 Contact WhatsApp", reply_markup=keyboard)
    schedule_deletion(sent)


@dp.callback_query(F.data == "horraire")
async def horraire_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    sent = await callback.message.answer(text="Midi - minuit")
    schedule_deletion(sent)


@dp.message(Command("stats"))
async def stats_handler(message: types.Message) -> None:
    """Show total registered users (admin only)."""
    if not is_admin(message.from_user.id):
        return
    count = user_count()
    sent = await message.answer(f"👥 Utilisateurs enregistrés : *{count}*", parse_mode="Markdown")
    schedule_deletion(sent)


@dp.message(Command("broadcast"))
async def broadcast_handler(message: types.Message) -> None:
    """
    Send a message to all registered users.
    Usage: /broadcast Votre texte ici
    Admin only.
    """
    if not is_admin(message.from_user.id):
        return

    # Extract the text after /broadcast
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Usage : /broadcast <message>")
        return

    broadcast_text = parts[1]
    users = get_all_users()

    sent_count = 0
    failed_count = 0

    for user in users:
        try:
            await bot.send_message(chat_id=user["chat_id"], text=broadcast_text)
            sent_count += 1
            await asyncio.sleep(0.05)  # stay within Telegram rate limits
        except (TelegramBadRequest, TelegramForbiddenError):
            failed_count += 1  # user blocked the bot or chat not found
        except Exception as e:
            logger.warning("Broadcast failed for chat_id=%s: %s", user["chat_id"], e)
            failed_count += 1

    report = (
        f"📢 Broadcast terminé\n"
        f"✅ Envoyé : {sent_count}\n"
        f"❌ Échec  : {failed_count}"
    )
    await message.answer(report)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    init_db()
    logger.info("Database initialised.")
    logger.info("Starting bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add it as a secret in your Replit project."
        )
    asyncio.run(main())
