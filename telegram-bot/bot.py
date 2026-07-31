import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

# Remove all whitespace (spaces, newlines, tabs) in case the token was pasted with extra characters
BOT_TOKEN = "".join((os.environ.get("BOT_TOKEN") or "").split())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🥷 Ouvrir le Shop",
                    web_app=WebAppInfo(url="https://www.guardiola66.com/login"),
                )
            ]
        ]
    )

    video_path = os.path.join(os.path.dirname(__file__), "welcome.mp4")

    if not os.path.exists(video_path):
        # Fallback: send only text if the video file is missing
        logger.warning("welcome.mp4 not found — sending text only.")
        await message.answer(
            text=(
                "👋 Bienvenue sur la mini-app !\n\n"
                "Clique sur le bouton ci-dessous pour ouvrir le shop."
            ),
            reply_markup=keyboard,
        )
        return

    video = FSInputFile(video_path)
    await message.answer_video(
        video=video,
        caption=(
            "👋 Bienvenue sur la mini-app !\n\n"
            "Clique sur le bouton ci-dessous pour ouvrir le shop."
        ),
        reply_markup=keyboard,
    )


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
    await message.answer(
        text="📱 Contact WhatsApp",
        reply_markup=keyboard,
    )


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
