"""Точка входа hub-бота.

Поддерживает два режима:
- polling (default): bot опрашивает api.telegram.org. Подходит для локальной разработки
  и серверов где открыт ТОЛЬКО исходящий канал (Россия).
- webhook: Telegram POST'ит к нам на https://<DOMAIN>/webhook. Требует открытого 443.
  Быстрее (нет polling-latency) и эффективнее по ресурсам.

Структура модулей описана в README.
"""

import asyncio

from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from core import (
    BOT_MODE,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_URL,
    bot,
    dp,
    log,
)
import handlers  # noqa: F401  регистрирует все @dp.* через handlers/__init__.py
from services.scheduler import task_scheduler


SLASH_COMMANDS = [
    BotCommand(command="memory", description="Память: вкл/выкл запоминания фактов"),
    BotCommand(command="network", description="Интернет: вкл/выкл поиск через Рой"),
    BotCommand(command="disclaimer", description="Подпись «🤖 Oblivion Assistant» в Business"),
    BotCommand(command="help", description="Что я умею и как со мной говорить"),
]


async def _setup_bot() -> None:
    """Один раз при старте: регистрируем меню slash-команд."""
    me = await bot.get_me()
    log.info("oblivion online as @%s (id=%d, mode=%s)", me.username, me.id, BOT_MODE)
    try:
        await bot.set_my_commands(SLASH_COMMANDS)
        log.info("registered %d slash commands", len(SLASH_COMMANDS))
    except Exception:
        log.exception("failed to register slash commands (not fatal)")


async def run_polling() -> None:
    await _setup_bot()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
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


async def _on_startup_webhook(_bot) -> None:
    await _setup_bot()
    if WEBHOOK_URL:
        full_url = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(
            full_url,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        log.info("webhook registered: %s", full_url)


async def _start_scheduler_background(_app: web.Application) -> None:
    """aiohttp on_startup: фоновый scheduler запускается параллельно webhook-у."""
    _app["scheduler_task"] = asyncio.create_task(task_scheduler())


async def _stop_scheduler_background(_app: web.Application) -> None:
    task = _app.get("scheduler_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def run_webhook() -> None:
    dp.startup.register(_on_startup_webhook)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(_start_scheduler_background)
    app.on_cleanup.append(_stop_scheduler_background)

    log.info("starting webhook server on 0.0.0.0:%d, path=%s", WEBHOOK_PORT, WEBHOOK_PATH)
    web.run_app(app, host="0.0.0.0", port=WEBHOOK_PORT)


def main() -> None:
    if BOT_MODE == "webhook":
        run_webhook()
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
