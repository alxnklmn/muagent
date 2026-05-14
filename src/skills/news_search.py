"""Поиск новостей через research-specialist бота (Tavily news topic).

Пока специалист обрабатывает — показывает прогресс в placeholder.
"""

from services.swarm import call_specialist


name = "news_search"
description = (
    "поиск свежих новостей по теме через специалист-бота. используй когда "
    "владелец просит новости, последние события, что-то из СМИ. "
    "возвращает короткую сводку + список новостных статей со ссылками."
)
schema = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "тема новостей, например 'AI agents', 'Telegram update', 'крипта'",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}
reads = []
writes = []
external_network = True


async def _show_progress(ctx, text: str) -> None:
    if not ctx.progress_message:
        return
    try:
        await ctx.progress_message.edit_text(text)
    except Exception:
        pass


async def handle(args, ctx):
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}

    short_query = query if len(query) <= 60 else query[:57] + "..."
    await _show_progress(ctx, f"🐝 Рой ищет свежие новости: «{short_query}»")

    result = await call_specialist(
        "research",
        "news",
        {"query": query, "max_results": 5},
        timeout=20.0,
    )

    if result.get("ok"):
        await _show_progress(ctx, "🐝 Рой вернул новости, оформляю...")
    return result
