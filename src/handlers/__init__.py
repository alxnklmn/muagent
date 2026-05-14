"""Хендлеры aiogram. Импорт модулей здесь регистрирует их через @dp.* декораторы.

Импортировать этот пакет нужно ОДИН раз — из bot.py перед dp.start_polling.

ВАЖНО: порядок имеет значение. aiogram проверяет хендлеры по порядку
регистрации, первый match выигрывает. specialist_responses ДОЛЖЕН быть
раньше owner_dm, иначе bot-to-bot сообщения попадут в обычный DM-обработчик.
"""

from . import (  # noqa: F401
    callbacks,
    connection,
    specialist_responses,
    owner_dm,
    business_msg,
)

__all__ = [
    "callbacks",
    "connection",
    "specialist_responses",
    "owner_dm",
    "business_msg",
]
