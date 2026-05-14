"""Точка входа.

Структура проекта после E.5.3:
  core         — bot, dp, llm, log + env-константы
  states       — STATE_* константы онбординга
  parsers      — regex pre-фильтры (быстрые без LLM)
  ui           — inline-клавиатуры + текстовые шаблоны
  prompting    — сборка system promptов с identity и tools manifestом
  services/
    time_parser    — парсинг 'через N минут', 'завтра' и т.п.
    tracks         — curated tracks.json (временная заглушка)
    onboarding     — диалог первичной настройки
    messaging      — task_voice (LLM microcopy)
    llm_runner     — единый pass с function-calling
    outbound       — отправка pending drafts + сохранение контактов
    scheduler      — фоновые task reminders + proactive
  handlers/
    connection     — business_connection
    owner_dm       — DM от владельца (онбординг и chat-mode)
    business_msg   — incoming в Business-чатах
    callbacks      — inline-кнопки
  skills/          — tool-calling units, авто-подхват реестром
  db.py            — SQLite слой
"""

import asyncio

from core import bot, dp, log
import handlers  # noqa: F401  импорт пакета регистрирует все @dp.* через handlers/__init__.py
from services.scheduler import task_scheduler


async def main() -> None:
    me = await bot.get_me()
    log.info("oblivion online as @%s (id=%d)", me.username, me.id)
    scheduler_task = asyncio.create_task(task_scheduler())
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
