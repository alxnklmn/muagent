"""Скачать видео по ссылке через video-specialist бота (swarm).

Видео доставляется владельцу НАПРЯМУЮ от @oblvhordex2_bot. Telegram требует
чтобы пользователь хотя бы раз нажал /start у бота — иначе бот не может
инициировать чат. Если владелец первый раз, skill вернёт owner_not_started,
hub должен прислать подсказку: «нажми /start @oblvhordex2_bot».
"""

from services.swarm import call_specialist


name = "download_video"
description = (
    "скачать видео по ссылке (Instagram / TikTok / YouTube / VK / Twitter и т.п.) "
    "и отправить владельцу напрямую от video-specialist бота. "
    "вызывай когда владелец дал ссылку на видео и просит скачать. "
    "ПРИМЕЧАНИЕ: видео придёт владельцу от @oblvhordex2_bot, а не от тебя. "
    "если владелец первый раз использует эту функцию, skill вернёт error=owner_not_started — "
    "тогда сообщи владельцу что нужно один раз нажать /start @oblvhordex2_bot."
)
schema = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "прямая URL видео на одной из поддерживаемых платформ",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}
reads = []
writes = []
external_network = True


async def handle(args, ctx):
    url = (args.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "url_required"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "invalid_url", "hint": "ссылка должна начинаться с http(s)://"}

    return await call_specialist(
        "video",
        "download",
        {"url": url, "owner_id": ctx.owner_id},
        timeout=120.0,  # download может занять до минуты на большом видео
    )
