import asyncio
import html as html_mod
import logging
import os
import re
import signal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest, TelegramConflictError, TelegramForbiddenError
from aiogram.methods import GetUpdates
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from database import (
    HEARTBEAT_STALE_SECS,
    clear_bot_heartbeat,
    clear_broadcast_messages,
    clear_daily_messages,
    get_all_broadcast_messages,
    get_all_daily_messages,
    get_all_users,
    get_bot_heartbeat,
    get_config,
    init_db,
    log_visit,
    register_user_atomic,
    save_broadcast_message,
    save_daily_message,
    set_bot_heartbeat,
    set_config,
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


async def _notify_admin_reliable(
    user: types.User,
    is_new: bool,
    total: int,           # exact count from the atomic DB transaction — no re-read
) -> None:
    """
    Send the admin notification for a /start event.
    • total is passed in (not re-read) — single source of truth, no race.
    • Retries up to 3 times with exponential back-off on Telegram API errors.
    • Every attempt and failure is logged.
    """
    if not ADMIN_ID:
        return
    now   = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    # html.escape() on ALL user-supplied strings — prevents Telegram parse errors
    # when names/usernames contain _ * ` [ (Markdown special chars).
    # We use HTML mode which is safer: only <>&" need escaping, and we control it.
    fname = html_mod.escape(user.first_name or "—")
    uname = html_mod.escape(f"@{user.username}" if user.username else "—")
    emoji = "🆕" if is_new else "🔄"
    label = "Nouvel utilisateur" if is_new else "Utilisateur existant"
    text  = (
        f"{emoji} <b>{label}</b>\n"
        f"👤 Prénom : {fname}\n"
        f"📛 Username : {uname}\n"
        f"🆔 User ID : <code>{user.id}</code>\n"
        f"📅 Date : {now}\n"
        f"📊 Total inscrits : <b>{total}</b>"
    )
    for attempt in range(1, 4):
        logger.info(
            "/start NOTIFY SENDING  user_id=%s  attempt=%d/3  admin_id=%s",
            user.id, attempt, ADMIN_ID,
        )
        try:
            result = await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
            logger.info(
                "/start NOTIFY OK  user_id=%s  total=%d  attempt=%d  msg_id=%s",
                user.id, total, attempt, result.message_id,
            )
            return
        except Exception:
            wait = 2 ** attempt          # 2 s, 4 s, 8 s
            if attempt < 3:
                logger.warning(
                    "/start NOTIFY FAILED  attempt=%d/3  user_id=%s  retry_in=%ds — traceback:",
                    attempt, user.id, wait,
                    exc_info=True,         # prints full traceback
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "/start NOTIFY ABANDONED  user_id=%s  all 3 attempts failed — traceback:",
                    user.id,
                    exc_info=True,         # full traceback on final failure
                )

# ── Keyboards ─────────────────────────────────────────────────────────────────

def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📲 Ouvrir le menu",
                web_app=WebAppInfo(url=os.environ.get("MINIAPP_URL", "https://www.guardiola66.com/login")),
            )],
            [InlineKeyboardButton(
                text="📞 Contact",
                url="https://wa.me/212625902052",
            )],
            [InlineKeyboardButton(
                text="🕘 horraire",
                callback_data="horraire",
            )],
            [InlineKeyboardButton(
                text="📢 Canal",
                url="https://t.me/+lhdKsCF5TW00NTg0",
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

@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    global _welcome_file_id
    loop = asyncio.get_event_loop()
    t0   = loop.time()
    user = message.from_user

    # ── [1] Diagnostics ───────────────────────────────────────────────────────
    now_utc    = datetime.now(timezone.utc)
    update_age = (now_utc - message.date.replace(tzinfo=timezone.utc)).total_seconds()
    logger.info("/start RECEIVED  user_id=%s  update_age=%.1fs  cached=%s",
                user.id if user else "?", update_age, _welcome_file_id is not None)

    # ── [2] DB: atomic register + count (~1–2 ms, sync, before reply) ─────────
    #   register_user_atomic does INSERT OR IGNORE + COUNT in one transaction,
    #   guaranteeing the returned total is exactly consistent with the insert.
    if user:
        is_new, total = register_user_atomic(
            user_id    = user.id,
            chat_id    = message.chat.id,
            first_name = user.first_name or "",
            username   = user.username,
        )
        log_visit(user.id)
        status = "CRÉÉ" if is_new else "EXISTANT"
        logger.info(
            "/start USER %s  user_id=%s  first_name=%r  username=%r  total_users=%d",
            status, user.id, user.first_name, user.username, total,
        )
    else:
        is_new, total = False, user_count()
        logger.warning("/start NO USER in message — skipping DB write")

    # ── [3] Send reply immediately ─────────────────────────────────────────────
    t2   = loop.time()
    name = (user.first_name if user and user.first_name else None) or \
           (user.username   if user and user.username   else None)
    text       = f"👋 Bienvenue sur la mini App , {name} !" if name \
                 else "👋 Bienvenue sur la mini App !"
    keyboard   = start_keyboard()
    photo_path = os.path.join(os.path.dirname(__file__), "welcome.jpg")

    if _welcome_file_id:
        sent = await message.answer_photo(
            photo=_welcome_file_id, caption=text, reply_markup=keyboard
        )
        logger.info("/start SENT (cached file_id)  api=%.0f ms", (loop.time() - t2) * 1000)
    elif os.path.exists(photo_path):
        sent = await message.answer_photo(
            photo=FSInputFile(photo_path), caption=text, reply_markup=keyboard
        )
        if sent.photo:
            _welcome_file_id = sent.photo[-1].file_id
            set_config("welcome_file_id", _welcome_file_id)
            logger.info("/start SENT (uploaded + file_id cached)  api=%.0f ms",
                        (loop.time() - t2) * 1000)
        else:
            logger.info("/start SENT (uploaded file)  api=%.0f ms", (loop.time() - t2) * 1000)
    else:
        sent = await message.answer(text=text, reply_markup=keyboard)
        logger.info("/start SENT (text only)  api=%.0f ms", (loop.time() - t2) * 1000)

    logger.info("/start TOTAL=%.0f ms  [update_age=%.1fs  total=%d  new=%s]",
                (loop.time() - t0) * 1000, update_age, total, is_new)
    schedule_deletion(sent)

    # ── [4] Admin notification — background task, 3 retry attempts ────────────
    if user:
        asyncio.create_task(_notify_admin_reliable(user, is_new, total))


@dp.message(Command("channel"))
async def channel_handler(message: types.Message) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📢 Rejoindre le canal",
            url="https://t.me/+lhdKsCF5TW00NTg0",
        )
    ]])
    sent = await message.reply(
        "Clique sur le bouton ci-dessous :",
        reply_markup=keyboard,
    )
    schedule_deletion(sent)


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

# ── Heartbeat helpers (dev/production conflict prevention) ────────────────────

def _production_is_active() -> bool:
    """
    Return True if a production heartbeat was written within the last
    HEARTBEAT_STALE_SECS seconds.  Both dev and production share the same
    PostgreSQL database, making this check reliable across containers.
    On any DB error we return False (fail-open: let dev proceed).
    """
    try:
        ts = get_bot_heartbeat("production")
        if ts is None:
            return False
        # Normalise to UTC-aware for comparison
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        logger.debug("Production heartbeat age: %.1f s (stale after %d s)", age, HEARTBEAT_STALE_SECS)
        return age < HEARTBEAT_STALE_SECS
    except Exception as exc:
        logger.warning("Could not check production heartbeat: %s", exc)
        return False  # assume no conflict if DB is unreachable


async def _heartbeat_loop(env: str, interval: int = 30) -> None:
    """Write a fresh heartbeat for *env* every *interval* seconds."""
    while True:
        try:
            set_bot_heartbeat(env)
        except Exception as exc:
            logger.warning("Heartbeat write failed: %s", exc)
        await asyncio.sleep(interval)


def _register_shutdown_heartbeat_clear(env: str) -> None:
    """
    On SIGTERM (container stop), clear the heartbeat so dev instances don't
    wait unnecessarily for HEARTBEAT_STALE_SECS to expire.
    """
    original = signal.getsignal(signal.SIGTERM)

    def _handler(signum, frame):
        try:
            clear_bot_heartbeat(env)
            logger.info("SIGTERM — %s heartbeat cleared.", env)
        except Exception:
            pass
        # Restore original handler and re-deliver the signal
        signal.signal(signal.SIGTERM, original if callable(original) else signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, _handler)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    global _welcome_file_id

    init_db()
    logger.info("Database initialised.")
    _welcome_file_id = get_config("welcome_file_id")
    if _welcome_file_id:
        logger.info("Loaded welcome_file_id from DB (length=%d)", len(_welcome_file_id))
    else:
        logger.info("No welcome_file_id in DB — will upload on first /start")

    bot_env = os.environ.get("BOT_ENV", "production")
    logger.info("Starting bot… (admin_id=%s, env=%s)", ADMIN_ID, bot_env)

    if bot_env == "development":
        # ── Dev: check shared DB heartbeat before even attempting to poll ─────
        if _production_is_active():
            logger.warning(
                "⚠️  PRODUCTION ACTIVE (heartbeat récent en base) — "
                "le workflow dev n'essaie pas de démarrer le polling pour éviter "
                "tout conflit. Arrêtez la production avant de relancer le dev."
            )
            return  # sortie propre, déterministe, indépendante de l'ordre de démarrage
        logger.info("No active production heartbeat — dev polling authorised.")
    else:
        # ── Production: write initial heartbeat and keep it alive ─────────────
        set_bot_heartbeat("production")
        asyncio.create_task(_heartbeat_loop("production"))
        _register_shutdown_heartbeat_clear("production")
        logger.info("Production heartbeat started.")

    # ── Sync the Menu button (blue Telegram button) to the same URL as the
    #    inline "Ouvrir le menu" button so both entry points hit the splash screen.
    miniapp_url = os.environ.get("MINIAPP_URL", "https://www.guardiola66.com/login")
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Menu",
                web_app=WebAppInfo(url=miniapp_url),
            )
        )
        logger.info("Menu button set to: %s", miniapp_url)
    except Exception:
        logger.warning("Could not set menu button — will retry on next restart", exc_info=True)

    # Start daily schedulers as background tasks
    asyncio.create_task(scheduler_open())
    asyncio.create_task(scheduler_close())

    # ── Custom polling loop — intercepts TelegramConflictError before aiogram's
    #    internal _listen_updates() retry loop swallows it.
    # ─────────────────────────────────────────────────────────────────────────
    POLLING_TIMEOUT   = 25    # long-poll wait time (seconds)
    CONFLICT_DELAY    = 10    # seconds before production retries after a 409
    ERROR_DELAY       = 3     # seconds before retrying any other transient error

    # Compute request-level timeout: session timeout + polling wait
    try:
        _session_timeout = bot.session.timeout or 30
    except Exception:
        _session_timeout = 30
    request_timeout = int(_session_timeout + POLLING_TIMEOUT)

    allowed_updates = dp.resolve_used_update_types()
    offset = 0

    # Emit startup lifecycle (FSM storage init, on_startup handlers, etc.)
    workflow_data = {
        "dispatcher": dp,
        "bots": (bot,),
        **dp.workflow_data,
    }
    await dp.emit_startup(bot=bot, **{k: v for k, v in workflow_data.items() if k not in ("bot",)})

    try:
        while True:
            get_updates = GetUpdates(
                offset=offset,
                timeout=POLLING_TIMEOUT,
                allowed_updates=allowed_updates,
            )
            try:
                updates = await bot(get_updates, request_timeout=request_timeout)
            except TelegramConflictError:
                if bot_env == "development":
                    logger.warning(
                        "⚠️  CONFLICT 409 en dev — une autre instance (production) "
                        "détient le verrou polling. Arrêt propre du workflow dev."
                    )
                    return
                # Production: conflict is transient (dev just started/restarted).
                # Wait for the other instance to release the lock, then retry.
                logger.warning(
                    "⚠️  CONFLICT 409 en production — attente %ds avant reprise…",
                    CONFLICT_DELAY,
                )
                await asyncio.sleep(CONFLICT_DELAY)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Erreur getUpdates: %s", exc, exc_info=True)
                await asyncio.sleep(ERROR_DELAY)
                continue

            for update in updates:
                if update.update_id >= offset:
                    offset = update.update_id + 1
                # Mirror aiogram's _polling(): use _process_update so handler
                # exceptions are contained and return-based TelegramMethod
                # responses are executed via silent_call_request.
                # Track in-flight tasks on dp._handle_update_tasks exactly as
                # aiogram does, enabling clean drain on shutdown.
                coro = dp._process_update(bot=bot, update=update, **dp.workflow_data)
                task = asyncio.create_task(coro)
                dp._handle_update_tasks.add(task)
                task.add_done_callback(dp._handle_update_tasks.discard)
    finally:
        await dp.emit_shutdown(
            bot=bot, **{k: v for k, v in workflow_data.items() if k not in ("bot",)}
        )
        await bot.session.close()


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    asyncio.run(main())
