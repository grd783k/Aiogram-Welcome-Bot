import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

from database import (
    clear_broadcast_messages,
    clear_daily_messages,
    get_all_broadcast_messages,
    get_all_daily_messages,
    get_all_users,
    init_db,
    log_visit,
    register_user,
    save_broadcast_message,
    save_daily_message,
    user_count,
    visits_today,
)

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN = "".join((os.environ.get("BOT_TOKEN") or "").split())

_admin_digits = re.sub(r"\D", "", os.environ.get("ADMIN_ID") or "")
try:
    ADMIN_ID: int | None = int(_admin_digits) if _admin_digits else None
except ValueError:
    ADMIN_ID = None

DELETE_AFTER = 3600       # seconds — auto-delete regular bot replies after 1 h
TZ = ZoneInfo("Europe/Paris")   # scheduler timezone
OPEN_HOUR   = 12          # 12:00 → send daily "shop open" message
CLOSE_HOUR  = 0           # 00:00 → delete daily message

DAILY_TEXT = (
    "🟢 Le shop est ouvert !\n"
    "🚚 Livraison disponible jusqu'à minuit."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# Cached after the first upload — avoids re-uploading welcome.jpg on every /start
_welcome_file_id: str | None = None

# ── FSM states ────────────────────────────────────────────────────────────────

class BroadcastState(StatesGroup):
    waiting_message = State()

# ── Auto-delete helper (regular replies) ──────────────────────────────────────

async def delete_after(message: Message, delay: int = DELETE_AFTER) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    except Exception as e:
        logger.debug("delete_after failed for msg %s: %s", message.message_id, e)


def schedule_deletion(message: Message) -> None:
    asyncio.create_task(delete_after(message))

# ── Admin helpers ─────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


async def notify_admin(user: types.User, is_new: bool) -> None:
    if not ADMIN_ID:
        return
    now = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    username_display = f"@{user.username}" if user.username else "—"
    total = user_count()
    emoji = "🆕" if is_new else "🔄"
    label = "Nouvel utilisateur" if is_new else "Utilisateur existant — a relancé le bot"
    text = (
        f"{emoji} *{label}*\n"
        f"👤 Prénom : {user.first_name or '—'}\n"
        f"📛 Username : {username_display}\n"
        f"🆔 User ID : `{user.id}`\n"
        f"📅 Date : {now}\n"
        f"📊 Total inscrits : *{total}*"
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning("notify_admin failed: %s", e)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📲 Ouvrir le menu",
                web_app=WebAppInfo(url="https://www.guardiola66.com/login"),
            )],
            [InlineKeyboardButton(
                text="📞 Contact",
                url="https://wa.me/212625902052",
            )],
            [InlineKeyboardButton(
                text="🕘 horraire",
                callback_data="horraire",
            )],
        ]
    )

# ── Daily scheduler ───────────────────────────────────────────────────────────

def _next_occurrence(hour: int, tz: ZoneInfo) -> datetime:
    """Return the next future datetime for `hour:00:00` in `tz`."""
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


async def send_daily_open() -> None:
    """12:00 — broadcast the daily shop-open message and save every message_id."""
    users = get_all_users()
    sent = 0
    failed = 0
    for user in users:
        try:
            msg = await bot.send_message(chat_id=user["chat_id"], text=DAILY_TEXT)
            save_daily_message(chat_id=user["chat_id"], message_id=msg.message_id)
            sent += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            failed += 1
        except Exception as e:
            logger.warning("daily_open send error chat_id=%s: %s", user["chat_id"], e)
            failed += 1
        await asyncio.sleep(0.05)   # respect Telegram rate limit
    logger.info("Daily OPEN sent: %d ok, %d failed", sent, failed)


async def delete_daily_messages() -> None:
    """00:00 — delete all saved daily messages."""
    records = get_all_daily_messages()
    deleted = 0
    failed  = 0
    for rec in records:
        try:
            await bot.delete_message(chat_id=rec["chat_id"], message_id=rec["message_id"])
            deleted += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            failed += 1   # already deleted or bot blocked — ignore
        except Exception as e:
            logger.warning("daily_close delete error: %s", e)
            failed += 1
        await asyncio.sleep(0.05)
    cleared = clear_daily_messages()
    logger.info("Daily CLOSE deleted: %d ok, %d failed (%d DB records cleared)", deleted, failed, cleared)


async def scheduler_open() -> None:
    """Loop: fire send_daily_open every day at OPEN_HOUR:00."""
    while True:
        target = _next_occurrence(OPEN_HOUR, TZ)
        wait   = (target - datetime.now(TZ)).total_seconds()
        logger.info("Next daily OPEN scheduled at %s (in %.0fs)", target.strftime("%d/%m %H:%M %Z"), wait)
        await asyncio.sleep(wait)
        await send_daily_open()


async def scheduler_close() -> None:
    """Loop: fire delete_daily_messages every day at CLOSE_HOUR:00."""
    while True:
        target = _next_occurrence(CLOSE_HOUR, TZ)
        wait   = (target - datetime.now(TZ)).total_seconds()
        logger.info("Next daily CLOSE scheduled at %s (in %.0fs)", target.strftime("%d/%m %H:%M %Z"), wait)
        await asyncio.sleep(wait)
        await delete_daily_messages()

# ── Handlers ──────────────────────────────────────────────────────────────────

async def _post_start(user: types.User, chat_id: int) -> None:
    """Background task: DB writes + admin notification after the reply is already sent."""
    is_new = register_user(
        user_id=user.id,
        chat_id=chat_id,
        first_name=user.first_name or "",
        username=user.username,
    )
    log_visit(user.id)
    logger.info("%s user: id=%s name=%s", "New" if is_new else "Returning", user.id, user.first_name)
    await notify_admin(user, is_new)


@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    global _welcome_file_id
    t0 = asyncio.get_event_loop().time()

    user = message.from_user
    name = (user.first_name if user and user.first_name else None) or \
           (user.username   if user and user.username   else None)
    text = f"👋 Bienvenue sur la mini App , {name} !" if name \
           else "👋 Bienvenue sur la mini App !"
    keyboard   = start_keyboard()
    photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")

    # ── Send reply immediately ────────────────────────────────────────────────
    if _welcome_file_id:
        # Cached file_id: Telegram serves the image from its CDN — no upload
        sent = await message.answer_photo(
            photo=_welcome_file_id, caption=text, reply_markup=keyboard
        )
    elif os.path.exists(photo_path):
        # First call: upload the file; cache the returned file_id for all future calls
        sent = await message.answer_photo(
            photo=FSInputFile(photo_path), caption=text, reply_markup=keyboard
        )
        if sent.photo:
            _welcome_file_id = sent.photo[-1].file_id
            logger.info("welcome.jpg file_id cached (%s…)", _welcome_file_id[:24])
    else:
        logger.warning("welcome.jpg not found — sending text only.")
        sent = await message.answer(text=text, reply_markup=keyboard)

    t1 = asyncio.get_event_loop().time()
    logger.info(
        "/start replied in %.0f ms  [cached=%s  user_id=%s]",
        (t1 - t0) * 1000,
        _welcome_file_id is not None,
        user.id if user else "?",
    )

    schedule_deletion(sent)

    # ── DB writes + admin notification run in background ─────────────────────
    if user:
        asyncio.create_task(_post_start(user, message.chat.id))


@dp.message(Command("contact"))
async def contact_handler(message: types.Message) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💬 WhatsApp", url="https://wa.me/212625902052")
    ]])
    sent = await message.answer(text="📱 Contact WhatsApp", reply_markup=keyboard)
    schedule_deletion(sent)


@dp.callback_query(F.data == "horraire")
async def horraire_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    sent = await callback.message.answer(text="Midi - minuit")
    schedule_deletion(sent)


@dp.message(Command("stats"))
async def stats_handler(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Accès refusé.")
        return
    total   = user_count()
    today   = visits_today()
    text = (
        "📊 *Statistiques du bot*\n\n"
        f"👥 Utilisateurs enregistrés : *{total}*\n"
        f"📅 Visites aujourd'hui (00:00 → 23:59) : *{today}*"
    )
    sent = await message.answer(text, parse_mode="Markdown")
    schedule_deletion(sent)


@dp.message(Command("deletebroadcast"))
async def deletebroadcast_handler(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Accès refusé.")
        return

    records = get_all_broadcast_messages()
    if not records:
        await message.answer("ℹ️ Aucun message de diffusion à supprimer.")
        return

    total   = len(records)
    deleted = 0
    failed  = 0

    progress = await message.answer(f"🗑 Suppression en cours… 0 / {total}")

    for i, rec in enumerate(records, start=1):
        try:
            await bot.delete_message(chat_id=rec["chat_id"], message_id=rec["message_id"])
            deleted += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            failed += 1   # already deleted or bot blocked — ignore silently
        except Exception as e:
            logger.warning("deletebroadcast error chat_id=%s: %s", rec["chat_id"], e)
            failed += 1

        if i % 10 == 0 or i == total:
            try:
                await progress.edit_text(f"🗑 Suppression en cours… {i} / {total}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    cleared = clear_broadcast_messages()
    try:
        await progress.delete()
    except Exception:
        pass

    report = (
        f"🗑 *Suppression terminée*\n"
        f"✅ Supprimé : {deleted}\n"
        f"❌ Déjà supprimé / inaccessible : {failed}\n"
        f"🗂 Enregistrements effacés : {cleared}"
    )
    sent = await message.answer(report, parse_mode="Markdown")
    schedule_deletion(sent)


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


@dp.message(Command("annuler"), BroadcastState.waiting_message)
async def broadcast_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Broadcast annulé.")


@dp.message(BroadcastState.waiting_message)
async def broadcast_send(message: Message, state: FSMContext) -> None:
    await state.clear()
    broadcast_text = message.text or message.caption or ""
    if not broadcast_text.strip():
        await message.answer("⚠️ Message vide. Broadcast annulé.")
        return

    users  = get_all_users()
    total  = len(users)
    sent_count  = 0
    failed_count = 0
    progress = await message.answer(f"📤 Envoi en cours… 0 / {total}")

    for i, user in enumerate(users, start=1):
        try:
            msg = await bot.send_message(chat_id=user["chat_id"], text=broadcast_text)
            save_broadcast_message(chat_id=user["chat_id"], message_id=msg.message_id)
            sent_count += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            failed_count += 1
        except Exception as e:
            logger.warning("broadcast error chat_id=%s: %s", user["chat_id"], e)
            failed_count += 1
        if i % 10 == 0 or i == total:
            try:
                await progress.edit_text(f"📤 Envoi en cours… {i} / {total}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    try:
        await progress.delete()
    except Exception:
        pass

    report = (
        f"📢 *Broadcast terminé*\n"
        f"✅ Envoyé avec succès : {sent_count}\n"
        f"❌ Échecs (bloqués / inaccessibles) : {failed_count}"
    )
    sent = await message.answer(report, parse_mode="Markdown")
    schedule_deletion(sent)

# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    init_db()
    logger.info("Database initialised.")
    logger.info("Starting bot… (admin_id=%s)", ADMIN_ID)

    # Start daily schedulers as background tasks
    asyncio.create_task(scheduler_open())
    asyncio.create_task(scheduler_close())

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    asyncio.run(main())
