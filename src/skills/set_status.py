"""Установить текущий статус владельца (в отпуске, спит, занят).

Статус инжектится в business-промпт и помогает боту сообщать собеседникам
про текущее состояние владельца. Опционально ограничивается scope-ом тегов.
"""

from datetime import datetime, timedelta, timezone


name = "set_status"
description = (
    "установить или обновить текущий статус владельца (отпуск, сон, занят, фокус). "
    "статус автоматически инжектится в ответы владельца в business-чатах. "
    "можно указать срок (часы или дни) — статус сам погаснет когда выйдет время. "
    "можно указать scopes — список тегов контактов («work», «family» и т.п.), "
    "только им будет видна эта инфа. без scopes — для всех. "
    "используй когда владелец говорит «я в отпуске», «лёг спать», «весь день в фокусе» и т.п."
)
schema = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "короткое описание статуса, например «в отпуске», «сплю», «в фокусе на проекте»",
        },
        "hours": {
            "type": "integer",
            "description": "через сколько часов статус истечёт. если статус надолго — используй days вместо",
            "minimum": 1,
            "maximum": 240,
        },
        "days": {
            "type": "integer",
            "description": "через сколько дней статус истечёт",
            "minimum": 1,
            "maximum": 90,
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "список тегов контактов, кому показывать статус "
                "(например ['work']). пусто или null = всем"
            ),
        },
    },
    "required": ["text"],
    "additionalProperties": False,
}
reads = []
writes = ["settings"]
external_network = False


async def handle(args, ctx):
    text = (args.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text_required"}

    until_iso = None
    hours = args.get("hours")
    days = args.get("days")
    if hours:
        until_iso = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    elif days:
        until_iso = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    scopes = args.get("scopes")  # list[str] | None

    status = {
        "text": text,
        "until": until_iso,
        "scopes": scopes,
    }
    ctx.db.save_owner(ctx.owner_id, status=status)
    return {"ok": True, "status": status}
