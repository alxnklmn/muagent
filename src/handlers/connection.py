"""Обработчик business_connection — реакция на привязку/отвязку бота."""

from aiogram.types import BusinessConnection

from core import bot, dp, log
from db import db
from services.onboarding import GREETING
from states import STATE_AWAITING_NAME


@dp.business_connection()
async def on_business_connection(connection: BusinessConnection) -> None:
    owner_id = connection.user.id
    log.info(
        "business_connection: owner=%d enabled=%s id=%s",
        owner_id, connection.is_enabled, connection.id,
    )

    if connection.is_enabled:
        existing = db.get_owner(owner_id)
        rights = connection.rights
        can_reply = bool(rights and getattr(rights, "can_reply", False))
        db.save_owner(
            owner_id,
            business_connection_id=connection.id,
            can_reply=can_reply,
        )
        if not existing:
            db.set_owner_state(owner_id, STATE_AWAITING_NAME)
            try:
                await bot.send_message(chat_id=owner_id, text=GREETING)
            except Exception:
                log.exception("failed to send greeting DM to owner %d", owner_id)
        else:
            log.info("owner %d reconnected; not resending greeting", owner_id)
    else:
        log.info("connection disabled by owner %d", owner_id)
        db.save_owner(owner_id, can_reply=False)
