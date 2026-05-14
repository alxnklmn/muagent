"""Корневые объекты процесса: bot, dp, llm, log + env-константы.

Импортируется первым во всём проекте. Здесь же делаем load_dotenv до того,
как любые модули прочитают env (services.time_parser, например).
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from aiogram import Bot, Dispatcher  # noqa: E402  load_dotenv должен быть выше
from openai import AsyncOpenAI


BOT_TOKEN = os.environ["BOT_TOKEN"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat-v3.1")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

MAX_HISTORY = 40
MAX_ONBOARDING_HISTORY = 20
MAX_TOOL_ROUNDS = 5

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("oblivion")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
llm = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
