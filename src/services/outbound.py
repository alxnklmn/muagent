"""Реальная отправка pending outbound + сохранение контактов из Business-чатов."""

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import Message

from core import bot, log
from db import db


async def send_pending_outbound(owner_id: int) -> str:
    """Отправить сохранённый draft через business_connection. Возвращает
    человекочитаемое сообщение о результате — для прямого показа владельцу."""
    owner = db.get_owner(owner_id) or {}
    pending = owner.get("pending_outbound")
    if not pending:
        return "нет сообщения на отправку."

    business_connection_id = pending.get("business_connection_id")
    chat_id = pending.get("chat_id")
    text = pending.get("text")
    if not business_connection_id or not chat_id or not text:
        db.save_owner(owner_id, pending_outbound=None)
        return "черновик битый. собери заново."

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            business_connection_id=business_connection_id,
        )
    except TelegramRetryAfter as e:
        log.warning("rate-limited on outbound: retry after %ds", e.retry_after)
        return f"telegram ограничил скорость. попробуй через {e.retry_after} сек."
    except TelegramForbiddenError as e:
        log.warning("forbidden on outbound (owner=%d): %s", owner_id, e)
        db.save_owner(owner_id, pending_outbound=None)
        return (
            "не могу отправить — нет прав. "
            "проверь что бот всё ещё подключён к business в настройках telegram."
        )
    except TelegramBadRequest as e:
        log.warning("bad request on outbound (owner=%d): %s", owner_id, e)
        db.save_owner(owner_id, pending_outbound=None)
        msg = str(e).lower()
        if "chat not found" in msg:
            return "контакта больше нет или чат удалён. черновик стёр."
        if "message is too long" in msg:
            return "сообщение слишком длинное. сократи и попробуй заново."
        if "business_peer_usage_missing" in msg:
            return (
                "у этого контакта нет business-доступа для меня. "
                "возможно он в твоём excluded list в настройках telegram business, "
                "или у собеседника premium с ограничениями. написать ему я не смогу."
            )
        if "business_connection" in msg:
            return (
                "business-подключение для этого чата сейчас не активно. "
                "проверь Settings → Business → Chatbots."
            )
        return f"telegram отказался принять: {e}"
    except TelegramNetworkError as e:
        log.warning("network error on outbound: %s", e)
        return "сеть моргнула. попробуй ещё раз через секунду."
    except TelegramServerError as e:
        log.warning("telegram server error on outbound: %s", e)
        return "у telegram проблемы на их стороне. попробуй через минуту."
    except Exception as e:
        log.exception("unexpected error on outbound (owner=%d)", owner_id)
        return f"что-то отвалилось: {type(e).__name__}. логи покажут детали."

    db.save_owner(owner_id, pending_outbound=None)
    db.append_audit_log(
        owner_id,
        "send_message",
        {"chat_id": chat_id, "recipient": pending.get("recipient")},
        {"ok": True, "text": text},
    )
    return "отправил."


def save_business_contact(owner_id: int, message: Message, bc_id: str | None) -> None:
    chat = message.chat
    user = message.from_user
    username = getattr(chat, "username", None) or getattr(user, "username", None)
    first_name = getattr(chat, "first_name", None) or getattr(user, "first_name", None)
    last_name = getattr(chat, "last_name", None) or getattr(user, "last_name", None)
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    db.save_contact(
        owner_id,
        chat.id,
        chat_id=chat.id,
        user_id=user.id if user else None,
        username=username,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        business_connection_id=bc_id,
        last_seen_at=db.now_iso(),
    )
