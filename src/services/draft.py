"""Draft-mode для business-ответов.

Каждый contact имеет reply_mode:
- 'auto'   : бот отвечает сразу контакту (как раньше)
- 'draft'  : бот шлёт draft в DM владельца с inline-кнопками
- 'silent' : бот не отвечает вообще

Дефолт для НОВЫХ untagged-контактов — 'draft'. Когда владелец тегает контакт
через tag_contact (даёт relationship/tags) — переключаемся на 'auto' (доверие).

Pending draft хранится в contact record:
{
    "pending_draft": {
        "text":           "что отправить",
        "created_at":     "iso UTC",
        "bc_id":          "business_connection_id",
        "chat_id":        chat_id контакта,
        "source_text":    "что контакт прислал (для контекста)",
        "owner_msg_id":   message_id уведомления в DM владельца
    }
}
"""

import asyncio
from datetime import datetime, timezone

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import bot, log
from db import db


DRAFT_AUTOSEND_AFTER_SEC = 5 * 60  # 5 минут без подтверждения → авто-отправка


def reply_mode_for_contact(contact: dict | None) -> str:
    """Текущий reply_mode контакта (или 'draft' по дефолту для untagged-новичков)."""
    if contact is None:
        return "draft"
    mode = (contact.get("reply_mode") or "").strip().lower()
    if mode in ("auto", "draft", "silent"):
        return mode
    # дефолт: tagged → auto, untagged → draft
    has_trust_signal = bool(contact.get("tags") or contact.get("relationship"))
    return "auto" if has_trust_signal else "draft"


def draft_keyboard(contact_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data=f"draft:send:{contact_id}"),
                InlineKeyboardButton(text="✏️ Свой текст", callback_data=f"draft:custom:{contact_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"draft:cancel:{contact_id}"),
                InlineKeyboardButton(text="⚡ Авто с ним", callback_data=f"draft:auto:{contact_id}"),
            ],
        ]
    )


def _truncate(text: str, n: int = 220) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _contact_label(contact: dict, contact_id: int) -> str:
    return (
        f"@{contact['username']}"
        if contact.get("username")
        else (contact.get("full_name") or str(contact_id))
    )


async def store_draft_and_notify_owner(
    owner_id: int,
    contact_id: int,
    contact: dict,
    source_text: str,
    draft_text: str,
    bc_id: str,
) -> None:
    """Сохранить pending draft и уведомить владельца в DM с inline-кнопками."""
    label = _contact_label(contact, contact_id)
    notice = (
        f"📨 черновик для {label}\n\n"
        f"он написал: {_truncate(source_text, 220)}\n\n"
        f"ты ответишь:\n{draft_text}"
    )
    try:
        msg = await bot.send_message(
            chat_id=owner_id,
            text=notice,
            reply_markup=draft_keyboard(contact_id),
        )
        owner_msg_id = msg.message_id
    except Exception:
        log.exception("failed to notify owner about draft (owner=%d)", owner_id)
        return

    db.save_contact(
        owner_id,
        contact_id,
        pending_draft={
            "text": draft_text,
            "created_at": db.now_iso(),
            "bc_id": bc_id,
            "chat_id": contact.get("chat_id") or contact_id,
            "source_text": source_text[:500],
            "owner_msg_id": owner_msg_id,
        },
    )


async def deliver_pending_draft(
    owner_id: int,
    contact_id: int,
    via_callback: bool = False,
) -> tuple[bool, str]:
    """Отправить контакту pending draft. Возвращает (ok, message_for_owner)."""
    contact = db.get_contact(owner_id, contact_id)
    if not contact:
        return False, "контакт не найден."
    pending = contact.get("pending_draft")
    if not pending:
        return False, "черновика нет."

    text = pending.get("text") or ""
    bc_id = pending.get("bc_id")
    chat_id = pending.get("chat_id") or contact_id

    if not text or not bc_id:
        db.save_contact(owner_id, contact_id, pending_draft=None)
        return False, "черновик битый — стёр."

    try:
        await bot.send_message(
            chat_id=chat_id, text=text, business_connection_id=bc_id,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "business_peer_invalid" in msg or "business_peer_usage_missing" in msg:
            db.save_contact(owner_id, contact_id, pending_draft=None)
            return False, f"не могу отправить — {_contact_label(contact, contact_id)} в excluded или нет business-доступа."
        log.warning("telegram bad request on draft delivery: %s", e)
        return False, f"telegram отказался: {e}"
    except TelegramForbiddenError as e:
        log.warning("forbidden on draft delivery: %s", e)
        return False, "telegram запретил отправку."
    except TelegramNetworkError as e:
        return False, f"сеть моргнула: {e}"
    except Exception as e:
        log.exception("unexpected error on draft delivery")
        return False, f"что-то отвалилось: {type(e).__name__}"

    db.save_contact(owner_id, contact_id, pending_draft=None)
    db.append_audit_log(
        owner_id,
        "draft_delivered",
        {"contact_id": contact_id, "via_callback": via_callback},
        {"ok": True, "len": len(text)},
    )
    label = _contact_label(contact, contact_id)
    return True, f"✅ отправил {label}"


async def cancel_pending_draft(owner_id: int, contact_id: int) -> str:
    db.save_contact(owner_id, contact_id, pending_draft=None)
    contact = db.get_contact(owner_id, contact_id) or {}
    return f"❌ черновик для {_contact_label(contact, contact_id)} отменён"


async def switch_to_auto_and_deliver(owner_id: int, contact_id: int) -> str:
    """Переключить контакт в auto-mode и сразу отправить текущий draft."""
    db.save_contact(owner_id, contact_id, reply_mode="auto")
    ok, msg = await deliver_pending_draft(owner_id, contact_id, via_callback=True)
    contact = db.get_contact(owner_id, contact_id) or {}
    label = _contact_label(contact, contact_id)
    suffix = f"\n⚡ теперь {label} в авто-режиме — буду отвечать без подтверждений."
    return msg + suffix


async def auto_send_overdue_drafts() -> int:
    """Scheduler tick: pending drafts старше DRAFT_AUTOSEND_AFTER_SEC автоматически отправляются.

    Возвращает количество отправленных. Запускается из task_scheduler.
    """
    now = datetime.now(timezone.utc)
    sent = 0
    for owner_id_text in list(db.list_owners().keys()):
        owner_id = int(owner_id_text)
        contacts = db.list_contacts(owner_id)
        for contact_id_text, contact in contacts.items():
            pending = contact.get("pending_draft")
            if not pending:
                continue
            try:
                created = datetime.fromisoformat(pending["created_at"])
                age = (now - created).total_seconds()
            except Exception:
                continue
            if age < DRAFT_AUTOSEND_AFTER_SEC:
                continue

            contact_id = int(contact_id_text)
            log.info(
                "auto-sending overdue draft: owner=%d contact=%d age=%ds",
                owner_id, contact_id, int(age),
            )
            ok, _ = await deliver_pending_draft(owner_id, contact_id)
            if ok:
                sent += 1
                # уведомляем владельца в DM
                contact = db.get_contact(owner_id, contact_id) or {}
                label = _contact_label(contact, contact_id)
                try:
                    await bot.send_message(
                        chat_id=owner_id,
                        text=f"⏰ автоотправил {label} (висел >{DRAFT_AUTOSEND_AFTER_SEC // 60} мин без подтверждения)",
                    )
                except Exception:
                    log.warning("could not notify owner about autosend")
    return sent
