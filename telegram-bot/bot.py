import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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

BOT_TOKEN = "".join((os.environ.get("BOT_TOKEN") or "").split())

ADMIN_ID_RAW = "".join((os.environ.get("ADMIN_ID") or "").split())
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

DELETE_AFTER = 3600  # seconds (1 hour)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── FSM states ────────────────────────────────────────────────────────────────

class BroadcastState(StatesGroup):
    waiting_message = State()  # admin has sent /broadcast, waiting for the text

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
    return ADMIN_ID is not None and user_id == ADMIN_ID

# ── Admin notification ────────────────────────────────────────────────────────

async def notify_admin(user: types.User, is_new: bool) -> None:
    """Send a private Telegram notification to ADMIN_ID about a /start event."""
    from datetime import datetime, timezone

    username_display = f"@{user.username}" if user.username else "—"
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    total = user_count()

    if is_new:
        text = (
            "🆕 *Nouvel utilisateur*\n"
            f"👤 Prénom : {user.first_name or '—'}\n"
            f"📛 Username : {username_display}\n"
            f"🆔 User ID : `{user.id}`\n"
            f"📅 Date : {now}\n"
            f"📊 Total inscrits : *{total}*"
        )
    else:
        text = (
            "🔄 *Utilisateur existant — a relancé le bot*\n"
            f"👤 Prénom : {user.first_name or '—'}\n"
            f"📛 Username : {username_display}\n"
            f"🆔 User ID : `{user.id}`\n"
            f"📅 Date : {now}\n"
            f"📊 Total inscrits : *{total}*"
        )

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning("Could not notify admin: %s", e)


# ── Keyboards ─────────────────────────────────────────────────────────────────

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

# ── Handlers ──────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    user = message.from_user

    # Register user (INSERT OR IGNORE — no duplicates)
    if user:
        is_new = register_user(
            user_id=user.id,
            chat_id=message.chat.id,
            first_name=user.first_name or "",
            username=user.username,
        )
        logger.info(
            "%s user: id=%s name=%s",
            "New" if is_new else "Returning",
            user.id,
            user.first_name,
        )
        # Notify admin
        if ADMIN_ID:
            await notify_admin(user, is_new)

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
        await message.answer("⛔ Accès refusé.")
        return
    count = user_count()
    sent = await message.answer(f"👥 Utilisateurs enregistrés : *{count}*", parse_mode="Markdown")
    schedule_deletion(sent)


# ── Broadcast — step 1 : /broadcast command ───────────────────────────────────

@dp.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Accès refusé.")
        return

    await state.set_state(BroadcastState.waiting_message)
    await message.answer(
        "✉️ Envoie le texte à diffuser à tous les utilisateurs.\n"
        "(/annuler pour abandonner)"
    )


# ── Broadcast — cancel ────────────────────────────────────────────────────────

@dp.message(Command("annuler"), BroadcastState.waiting_message)
async def broadcast_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Broadcast annulé.")


# ── Broadcast — step 2 : receive the text and send to all users ───────────────

@dp.message(BroadcastState.waiting_message)
async def broadcast_send(message: Message, state: FSMContext) -> None:
    await state.clear()

    broadcast_text = message.text or message.caption or ""
    if not broadcast_text.strip():
        await message.answer("⚠️ Message vide. Broadcast annulé.")
        return

    users = get_all_users()
    total = len(users)
    sent_count = 0
    failed_count = 0

    progress = await message.answer(f"📤 Envoi en cours… 0 / {total}")

    for i, user in enumerate(users, start=1):
        try:
            await bot.send_message(chat_id=user["chat_id"], text=broadcast_text)
            sent_count += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            # User blocked the bot or chat no longer exists — skip silently
            failed_count += 1
        except Exception as e:
            logger.warning("Broadcast error for chat_id=%s: %s", user["chat_id"], e)
            failed_count += 1

        # Update progress every 10 users
        if i % 10 == 0 or i == total:
            try:
                await progress.edit_text(f"📤 Envoi en cours… {i} / {total}")
            except Exception:
                pass

        await asyncio.sleep(0.05)  # stay within Telegram rate limits (20 msg/s)

    report = (
        f"📢 *Broadcast terminé*\n"
        f"✅ Envoyé avec succès : {sent_count}\n"
        f"❌ Échecs (bloqués / inaccessibles) : {failed_count}"
    )

    try:
        await progress.delete()
    except Exception:
        pass

    sent = await message.answer(report, parse_mode="Markdown")
    schedule_deletion(sent)  # rapport supprimé après 1 heure


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    init_db()
    logger.info("Database initialised.")
    logger.info("Starting bot… (admin_id=%s)", ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add it as a secret in your Replit project."
        )
    asyncio.run(main())
