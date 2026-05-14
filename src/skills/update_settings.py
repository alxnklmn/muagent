name = "update_settings"
description = (
    "изменить настройки бота. передавай только те поля которые надо изменить.\n"
    "- proactive_enabled: может ли бот сам инициировать сообщения\n"
    "- music_enabled: можно ли отправлять треки\n"
    "- gifs_enabled: можно ли отправлять гифки\n"
    "- daily_checkin_enabled: утренний чекин\n"
    "- proactive_daily_budget: сколько раз в день бот может писать сам\n"
    "- paused: бот молчит везде (true=пауза, false=снять)\n"
    "- disclaimer: при первом ответе сообщать собеседнику что отвечает AI"
)
schema = {
    "type": "object",
    "properties": {
        "proactive_enabled": {"type": "boolean"},
        "music_enabled": {"type": "boolean"},
        "gifs_enabled": {"type": "boolean"},
        "daily_checkin_enabled": {"type": "boolean"},
        "proactive_daily_budget": {"type": "integer", "minimum": 0, "maximum": 20},
        "paused": {"type": "boolean"},
        "disclaimer": {"type": "boolean"},
    },
    "additionalProperties": False,
}
reads = ["settings"]
writes = ["settings"]
external_network = False


async def handle(args, ctx):
    updates = {key: value for key, value in args.items() if value is not None}
    if not updates:
        return {"ok": False, "error": "no_settings_to_update"}

    ctx.db.save_settings(ctx.owner_id, **updates)
    return {"ok": True, "updated": updates}
