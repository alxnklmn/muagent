"""Создать повторяющуюся задачу (digest / monitoring) — например ежедневная сводка новостей в 9 утра."""

name = "schedule_recurring"
description = (
    "поставить повторяющуюся задачу: ежедневная сводка новостей / поиск / отчёт. "
    "примеры триггеров: «каждый день в 9 утра присылай новости про AI», "
    "«каждое утро в 8 пиши главное по крипте», «по будням в 18 шли сводку по рынкам». "
    "kind: 'news' для новостной сводки, 'web' для общего поиска. "
    "после установки специалист-бот будет каждый день в указанное время бежать запрос "
    "и присылать owner-у форматированную сводку в DM."
)
schema = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["news", "web"],
            "description": "news = свежие новости по теме (через Tavily news), web = общий поиск",
        },
        "query": {
            "type": "string",
            "description": "тема запроса: 'крипта', 'AI agents', 'Telegram Business'",
        },
        "hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": "час локального времени, в который запускать (0-23)",
        },
        "minute": {
            "type": "integer",
            "minimum": 0,
            "maximum": 59,
            "description": "минута, по умолчанию 0",
        },
    },
    "required": ["kind", "query", "hour"],
    "additionalProperties": False,
}
reads = []
writes = ["settings"]
external_network = False  # сам по себе scheduling не сетевой, выполнение позже — отдельно


async def handle(args, ctx):
    kind = args.get("kind")
    query = (args.get("query") or "").strip()
    hour = args.get("hour")
    minute = args.get("minute", 0) or 0

    if kind not in ("news", "web"):
        return {"ok": False, "error": "kind_must_be_news_or_web"}
    if not query:
        return {"ok": False, "error": "query_required"}
    if not isinstance(hour, int) or not (0 <= hour <= 23):
        return {"ok": False, "error": "hour_must_be_0_23"}
    if not isinstance(minute, int) or not (0 <= minute <= 59):
        return {"ok": False, "error": "minute_must_be_0_59"}

    job = ctx.db.add_recurring_job(
        owner_id=ctx.owner_id,
        kind=kind,
        query=query,
        hour_local=hour,
        minute_local=minute,
    )
    return {
        "ok": True,
        "job_id": job["id"],
        "kind": kind,
        "query": query,
        "time": f"{hour:02d}:{minute:02d}",
    }
