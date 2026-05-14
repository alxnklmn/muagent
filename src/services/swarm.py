"""Bot-to-bot dispatcher для делегирования задач специалист-ботам.

Pattern: hub отправляет JSON в DM специалист-бота, ждёт асинхронный ответ
с тем же request_id. Под капотом — обычный sendMessage между ботами через
Telegram (требует Bot-to-Bot Communication Mode включенным у обоих).

ВАЖНО: данные идут через Telegram-сервера в открытом виде между ботами,
поэтому в скиллах не передаём PII владельца без необходимости.
"""

import asyncio
import json
import uuid

from core import bot, log


# whitelist специалистов: имя → @username (без @ в коде, добавляется при отправке)
SPECIALISTS: dict[str, str] = {
    "research": "oblvhordex1_bot",  # web search + news через Tavily
    "video": "oblvhordex2_bot",  # yt-dlp Instagram/TikTok/YouTube → owner direct
}

# pending requests: request_id → Future (set_result когда придёт ответ)
_pending: dict[str, asyncio.Future] = {}


def trusted_specialist_usernames() -> set[str]:
    """Используется hub-handler-ом для фильтрации входящих от ботов."""
    return set(SPECIALISTS.values())


async def call_specialist(
    specialist: str,
    method: str,
    args: dict,
    timeout: float = 25.0,
) -> dict:
    """Послать запрос специалист-боту, ждать ответ через b2b.

    Returns dict с полями skill-результата. Если timeout — {ok: false, error: timeout}.
    """
    target_username = SPECIALISTS.get(specialist)
    if not target_username:
        return {"ok": False, "error": f"unknown_specialist:{specialist}"}

    req_id = str(uuid.uuid4())
    payload = {"id": req_id, "method": method, "args": args}

    future: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending[req_id] = future

    try:
        await bot.send_message(
            chat_id=f"@{target_username}",
            text=json.dumps(payload, ensure_ascii=False),
        )
    except Exception as e:
        _pending.pop(req_id, None)
        log.exception("failed to send to specialist @%s", target_username)
        return {"ok": False, "error": f"send_failed:{type(e).__name__}", "message": str(e)}

    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        log.warning(
            "specialist @%s did not respond in %ss (req_id=%s)",
            target_username, timeout, req_id,
        )
        return {"ok": False, "error": "timeout", "specialist": specialist}
    finally:
        _pending.pop(req_id, None)


def deliver_specialist_response(payload: dict) -> bool:
    """Положить ответ специалиста в Future соответствующего request_id.

    Returns True если успешно сматчено, False если запроса нет (мог быть timeout-нут).
    """
    req_id = payload.get("id")
    if not req_id:
        log.warning("specialist response missing id field: %r", payload)
        return False

    future = _pending.get(req_id)
    if not future:
        log.warning("no pending request for req_id=%s — already timed out?", req_id)
        return False

    if not future.done():
        # из payload убираем id перед передачей наверх — id служебный
        result = {k: v for k, v in payload.items() if k != "id"}
        future.set_result(result)
    return True
