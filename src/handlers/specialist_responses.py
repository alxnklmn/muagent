"""Handler для входящих сообщений от других ботов (специалистов в swarm).

ВАЖНО: этот handler должен быть зарегистрирован РАНЬШЕ owner_dm,
иначе owner_dm перехватит сообщения от bot.is_bot=true и попытается
их обработать как DM владельца.
"""

import json

from aiogram import F
from aiogram.types import Message

from core import dp, log
from services.swarm import deliver_specialist_response, trusted_specialist_usernames


@dp.message(F.from_user.is_bot, F.text)
async def on_specialist_message(message: Message) -> None:
    if not message.from_user:
        return

    username = message.from_user.username
    trusted = trusted_specialist_usernames()
    if username not in trusted:
        log.warning(
            "rejecting message from unknown bot @%s (trusted: %s)",
            username, trusted,
        )
        return

    try:
        payload = json.loads(message.text)
    except json.JSONDecodeError:
        log.warning("invalid json from specialist @%s: %r", username, message.text[:200])
        return

    delivered = deliver_specialist_response(payload)
    if not delivered:
        log.debug(
            "specialist @%s response not matched to pending request (req_id=%s)",
            username, payload.get("id"),
        )
