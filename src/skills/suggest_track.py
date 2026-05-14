from services.tracks import pick_track


name = "suggest_track"
description = (
    "предложить трек под настроение. mood: focus (концентрация), "
    "calm (успокоиться), night (ночь), drive (взбодриться), done (завершение). "
    "используй когда владелец просит музыку. если music_enabled выключен в настройках — "
    "скилл вернёт ошибку music_disabled, не вызывай его."
)
schema = {
    "type": "object",
    "properties": {
        "mood": {
            "type": "string",
            "enum": ["focus", "calm", "night", "drive", "done"],
            "description": "настроение под которое нужен трек",
        }
    },
    "additionalProperties": False,
}
reads = ["settings"]
writes = []
external_network = False


async def handle(args, ctx):
    if not ctx.db.get_setting(ctx.owner_id, "music_enabled", True):
        return {"ok": False, "error": "music_disabled"}

    mood = args.get("mood") or "focus"
    track = pick_track(mood)
    return {
        "ok": True,
        "mood": mood,
        "title": track["title"],
        "url": track["url"],
        "note": track["note"],
    }
