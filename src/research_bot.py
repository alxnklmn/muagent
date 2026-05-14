"""Research specialist bot: web search + news через Tavily.

Это отдельный процесс (отдельный bot token, отдельный aiogram), который:
1. Слушает b2b-сообщения от hub-бота (@oblivionares_bot).
2. Парсит JSON {id, method, args}.
3. Обращается к Tavily API (search или news).
4. Отвечает JSON {id, ok, ...} обратно в hub.

Запуск: python src/research_bot.py (параллельно с bot.py).

ВАЖНО: оба бота должны иметь Bot-to-Bot Communication Mode ВКЛ в @BotFather.
Без этого Telegram не пропустит сообщения между ними.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from aiogram import Bot, Dispatcher, F  # noqa: E402
from aiogram.types import Message  # noqa: E402
from tavily import TavilyClient  # noqa: E402


RESEARCH_BOT_TOKEN = os.environ["RESEARCH_BOT_TOKEN"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

HUB_BOT_USERNAME = "oblivionares_bot"  # ждём сообщения только от него
MAX_RESPONSE_CHARS = 4000  # telegram message limit 4096

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("research-bot")

bot = Bot(token=RESEARCH_BOT_TOKEN)
dp = Dispatcher()
tavily = TavilyClient(api_key=TAVILY_API_KEY)


async def handle_search(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    max_results = int(args.get("max_results") or 5)

    # Tavily sdk synchronous → выполняем в thread, чтоб не блокировать event loop
    r = await asyncio.to_thread(
        tavily.search,
        query=query,
        max_results=max_results,
        include_answer=True,
    )
    return {
        "ok": True,
        "query": query,
        "answer": r.get("answer"),
        "results": [
            {
                "title": x.get("title"),
                "url": x.get("url"),
                "snippet": (x.get("content") or "")[:300],
            }
            for x in (r.get("results") or [])
        ],
    }


async def handle_news(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    max_results = int(args.get("max_results") or 5)

    r = await asyncio.to_thread(
        tavily.search,
        query=query,
        max_results=max_results,
        include_answer=True,
        topic="news",
    )
    return {
        "ok": True,
        "query": query,
        "answer": r.get("answer"),
        "results": [
            {
                "title": x.get("title"),
                "url": x.get("url"),
                "snippet": (x.get("content") or "")[:300],
            }
            for x in (r.get("results") or [])
        ],
    }


METHODS = {
    "search": handle_search,
    "news": handle_news,
}


def _shrink_result_if_too_big(result: dict) -> dict:
    """Telegram message ≤ 4096 chars. Если результат толще — режем results / snippet."""
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= MAX_RESPONSE_CHARS:
        return result

    # шаг 1: оставляем максимум 3 result-а
    if isinstance(result.get("results"), list):
        result["results"] = result["results"][:3]
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= MAX_RESPONSE_CHARS:
        return result

    # шаг 2: сокращаем snippet каждого до 150
    for item in result.get("results", []):
        if isinstance(item.get("snippet"), str):
            item["snippet"] = item["snippet"][:150]
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= MAX_RESPONSE_CHARS:
        return result

    # шаг 3: режем answer до 500
    if isinstance(result.get("answer"), str):
        result["answer"] = result["answer"][:500]
    return result


@dp.message(F.from_user.is_bot, F.text)
async def on_hub_message(message: Message) -> None:
    if not message.from_user:
        return

    sender = message.from_user.username
    if sender != HUB_BOT_USERNAME:
        log.warning("rejecting message from unknown bot @%s", sender)
        return

    try:
        payload = json.loads(message.text)
    except json.JSONDecodeError:
        log.warning("invalid json from hub: %r", message.text[:200])
        return

    req_id = payload.get("id")
    method = payload.get("method")
    args = payload.get("args") or {}

    if not req_id or not method:
        log.warning("missing id or method: %r", payload)
        return

    handler = METHODS.get(method)
    if not handler:
        result = {"id": req_id, "ok": False, "error": f"unknown_method:{method}"}
    else:
        try:
            inner = await handler(args)
            result = {"id": req_id, **inner}
        except Exception as e:
            log.exception("method %s failed", method)
            result = {"id": req_id, "ok": False, "error": f"{type(e).__name__}", "message": str(e)}

    result = _shrink_result_if_too_big(result)
    response_text = json.dumps(result, ensure_ascii=False)

    try:
        await bot.send_message(
            chat_id=f"@{HUB_BOT_USERNAME}",
            text=response_text,
        )
    except Exception:
        log.exception("failed to send response back to hub (req_id=%s)", req_id)


async def main() -> None:
    me = await bot.get_me()
    log.info(
        "research-bot online as @%s (id=%d, can_b2b=%s)",
        me.username, me.id, getattr(me, "can_connect_to_business", None),
    )
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
