"""Парсер натуральных выражений времени и форматирование дедлайнов.

Используется и в bot.py, и в skills/task_add. Логика была в bot.py до E.5.1.
"""

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Vladivostok"))
DEFAULT_TASK_HOUR = 9


def parse_due_text(due_text: str | None) -> str | None:
    """Перевести фразу вида 'через 10 минут', 'завтра в 18', 'сегодня' в ISO UTC.

    Возвращает None если фраза без срока или не распарсилась.
    """
    if not due_text:
        return None

    text = " ".join(due_text.casefold().strip().split())
    now = datetime.now(LOCAL_TZ)

    if text in {"без срока", "нет", "none"}:
        return None

    if "через" in text:
        parts = text.split()
        # форма "через минуту/час" без числа
        for part in parts:
            if part.startswith("мин"):
                return (now + timedelta(minutes=1)).astimezone(timezone.utc).isoformat()
            if part.startswith("час"):
                return (now + timedelta(hours=1)).astimezone(timezone.utc).isoformat()
        # форма "через N минут/часов/дней"
        for i, part in enumerate(parts):
            if part.isdigit() and i + 1 < len(parts):
                amount = int(part)
                unit = parts[i + 1]
                if unit.startswith("мин"):
                    return (now + timedelta(minutes=amount)).astimezone(timezone.utc).isoformat()
                if unit.startswith("час"):
                    return (now + timedelta(hours=amount)).astimezone(timezone.utc).isoformat()
                if unit.startswith("д"):
                    due = now + timedelta(days=amount)
                    due = due.replace(
                        hour=DEFAULT_TASK_HOUR,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    return due.astimezone(timezone.utc).isoformat()

    if "послезавтра" in text:
        due = now + timedelta(days=2)
    elif "завтра" in text:
        due = now + timedelta(days=1)
    elif "сегодня" in text:
        due = now
    else:
        return None

    hour = DEFAULT_TASK_HOUR
    minute = 0
    for token in text.replace(":", " ").split():
        if token.isdigit():
            value = int(token)
            if 0 <= value <= 23:
                hour = value
                break
    due = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        due = due + timedelta(days=1)
    return due.astimezone(timezone.utc).isoformat()


def format_due(due_at: str | None) -> str:
    if not due_at:
        return "без срока"
    due = datetime.fromisoformat(due_at).astimezone(LOCAL_TZ)
    return due.strftime("%d.%m %H:%M")


def clean_task_title(title: str) -> str:
    """Убрать слова-паразиты вроде 'напомни', 'пожалуйста' из названия задачи."""
    noise = {"пожалуйста", "плиз", "плз", "please", "напомни", "напомнить"}
    words = [word.strip(".,!?;:()[]{}\"'«»") for word in title.strip().split()]
    words = [word for word in words if word.casefold() not in noise]
    return " ".join(words).strip()
