"""Индикатор «бот думает»: постоянный typing + опциональный эмодзи-плейсхолдер.

Используется DM и Business handlers, чтобы пока LLM-pass идёт пользователь видел
живую активность (typing... в шапке чата + эмодзи-сообщение в DM, если разрешён).
"""

import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram.types import Message

from core import bot, log


# фразы которые видит владелец пока бот думает.
# random.choice — каждый раз новая, чтобы не было ощущения цикла.
# часть с текстом, часть только эмодзи. короткие, чтобы edit не лагал.
THINKING_EMOJIS = [
    "🤔",
    "💭 думаю...",
    "🧠 размышляю...",
    "✨ генерирую...",
    "👀 смотрю...",
    "⚡ обрабатываю...",
    "🎯 фокусируюсь...",
    "🌀 кручу мысли...",
    "💡 формулирую...",
    "⏳ секунду...",
    "🪄 колдую...",
    "🔮 предсказываю...",
    "📚 читаю контекст...",
    "🧩 собираю кусочки...",
    "🎨 рисую ответ...",
    "🚀 разгоняюсь...",
    "🐢 ползу аккуратно...",
    "☕ варю мысль...",
]


async def _refresh_typing(chat_id: int, business_connection_id: str | None) -> None:
    """Каждые ~4 секунды переотправляет typing-action, пока taska не отменят."""
    while True:
        try:
            await bot.send_chat_action(
                chat_id=chat_id,
                action="typing",
                business_connection_id=business_connection_id,
            )
        except Exception:
            # сеть могла отвалиться, попробуем через 4 секунды
            pass
        await asyncio.sleep(4)


@asynccontextmanager
async def thinking(
    chat_id: int,
    business_connection_id: str | None = None,
    show_placeholder: bool = False,
) -> AsyncIterator[Message | None]:
    """Контекстный менеджер: пока внутри блока, typing... не гаснет.

    Если show_placeholder=True (только для owner DM) — сначала отправляет
    эмодзи-сообщение и yield-ит его наружу. Caller должен либо `edit_text`
    плейсхолдер на финальный ответ, либо `delete()` его и отправить новое.

    Если show_placeholder=False (Business-чаты) — yield-ит None, caller сам
    шлёт ответ через bot.send_message с business_connection_id.

    Использование:
        async with thinking(chat.id, show_placeholder=True) as placeholder:
            reply = await run_llm_with_tools(...)

        if placeholder:
            await placeholder.edit_text(reply, reply_markup=keyboard)
        else:
            await bot.send_message(chat.id, reply, ...)
    """
    placeholder: Message | None = None
    if show_placeholder:
        try:
            placeholder = await bot.send_message(
                chat_id=chat_id,
                text=random.choice(THINKING_EMOJIS),
                business_connection_id=business_connection_id,
            )
        except Exception:
            log.warning("thinking placeholder send failed", exc_info=True)

    typing_task = asyncio.create_task(
        _refresh_typing(chat_id, business_connection_id)
    )
    try:
        yield placeholder
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


async def deliver_reply(
    chat_id: int,
    text: str,
    placeholder: Message | None,
    business_connection_id: str | None = None,
    reply_markup=None,
) -> Message:
    """Отправить финальный ответ.

    Если был placeholder — пытается отредактировать его. Если edit падает,
    делает fallback на send_message.
    Если placeholder == None — просто send_message.
    """
    if placeholder is not None:
        try:
            return await placeholder.edit_text(text, reply_markup=reply_markup)
        except Exception:
            log.warning("placeholder edit failed, sending fresh", exc_info=True)
            try:
                await placeholder.delete()
            except Exception:
                pass

    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        business_connection_id=business_connection_id,
        reply_markup=reply_markup,
    )


async def cleanup_placeholder(placeholder: Message | None) -> None:
    """Удалить placeholder если LLM ничего не вернул."""
    if placeholder is None:
        return
    try:
        await placeholder.delete()
    except Exception:
        pass
