"""Корневые объекты процесса: bot, dp, llm, log + env-константы.

Импортируется первым во всём проекте. Здесь же делаем load_dotenv до того,
как любые модули прочитают env (services.time_parser, например).
"""

import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from aiogram import Bot, Dispatcher  # noqa: E402  load_dotenv должен быть выше
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402


BOT_TOKEN = os.environ["BOT_TOKEN"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat-v3.1")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# proxy для всех исходящих HTTP-вызовов (api.telegram.org, openrouter.ai, tavily, ...)
# полезно на серверах с гео-блокировкой. формат: http://user:pass@host:port
OUTBOUND_PROXY = (os.environ.get("OUTBOUND_PROXY") or "").strip() or None

# режим запуска: polling — исходящий long-poll, webhook — Telegram POST'ит к нам
BOT_MODE = (os.environ.get("BOT_MODE") or "polling").lower().strip()
WEBHOOK_URL = (os.environ.get("WEBHOOK_URL") or "").strip()
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook").strip()
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8080"))

MAX_HISTORY = 40
MAX_ONBOARDING_HISTORY = 20
MAX_TOOL_ROUNDS = 5

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("oblivion")

# aiogram session с прокси (если задан) — для всех вызовов к api.telegram.org
_aiogram_session = AiohttpSession(proxy=OUTBOUND_PROXY) if OUTBOUND_PROXY else AiohttpSession()
bot = Bot(token=BOT_TOKEN, session=_aiogram_session)
dp = Dispatcher()

# openai (httpx) client с прокси — для вызовов к openrouter.ai
_httpx_client = httpx.AsyncClient(proxy=OUTBOUND_PROXY) if OUTBOUND_PROXY else None
llm = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    http_client=_httpx_client,
)

if OUTBOUND_PROXY:
    log.info("OUTBOUND_PROXY active — all egress goes through configured proxy")
