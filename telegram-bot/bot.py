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

# Remove all whitespace (spaces, newlines, tabs) in case the token was pasted with extra characters
BOT_TOKEN = "".join((os.environ.get("BOT_TOKEN") or "").split())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DELETE_AFTER = 3600  # seconds (1 hour)

# ── Auto-delete helper ────────────────────────────────────────────────────────

async def delete_after(message: Message, delay: int = DELETE_AFTER) -> None:
    """Wait `delay` seconds then silently delete `message`."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        # Message already deleted, or bot lacks permission — ignore
        pass
    except Exception as e:
        logger.debug("Could not delete message %s: %s", message.message_id, e)


def schedule_deletion(message: Message) -> None:
    """Fire-and-forget: schedule a message for deletion after DELETE_AFTER seconds."""
    asyncio.create_task(delete_after(message))


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
    text = "👋 Bienvenue sur la mini app guardiola"
    keyboard = start_keyboard()

    video_path = os.path.join(os.path.dirname(__file__), "welcome.mp4")

    if not os.path.exists(video_path):
        logger.warning("welcome.mp4 not found — sending text only.")
        sent = await message.answer(text=text, reply_markup=keyboard)
    else:
        video = FSInputFile(video_path)
        sent = await message.answer_video(video=video, caption=text, reply_markup=keyboard)

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
    await callback.answer()  # dismiss the loading spinner
    sent = await callback.message.answer(text="Midi - minuit")
    schedule_deletion(sent)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("Starting bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add it as a secret in your Replit project."
        )
    asyncio.run(main())
