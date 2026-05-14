"""Web search через research-specialist бота (swarm pattern).

Скилл не делает запрос сам — он шлёт b2b-сообщение @oblvhordex1_bot,
тот идёт в Tavily и возвращает результаты. Hub получает их через
handlers/specialist_responses.py.

Пока специалист думает — обновляет placeholder в DM владельца,
чтобы было видно «бот обращается к Рою» (вместо немой паузы).
"""

from services.swarm import call_specialist


name = "web_search"
description = (
    "поиск по интернету через специалист-бота. используй когда нужна актуальная "
    "информация которой нет в твоей памяти: текущие события, факты о компаниях, "
    "сравнения, документация, биографии. возвращает короткий ответ-сводку + "
    "список релевантных источников. для новостей используй news_search вместо."
)
schema = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "поисковый запрос, можно на любом языке",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}
reads = []
writes = []
external_network = True  # делегируем специалист-боту, который ходит в интернет


async def _show_progress(ctx, text: str) -> None:
    """Обновить placeholder в DM владельца, чтоб показать что обращаемся к Рою."""
    if not ctx.progress_message:
        return
    try:
        await ctx.progress_message.edit_text(text)
    except Exception:
        # placeholder могли уже удалить или edit не прошёл — не критично
        pass


async def handle(args, ctx):
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}

    short_query = query if len(query) <= 60 else query[:57] + "..."
    await _show_progress(ctx, f"🐝 спрашиваю Рой: «{short_query}»")

    result = await call_specialist(
        "research",
        "search",
        {"query": query, "max_results": 5},
        timeout=20.0,
    )

    if result.get("ok"):
        await _show_progress(ctx, "🐝 Рой ответил, собираю ответ...")
    return result
