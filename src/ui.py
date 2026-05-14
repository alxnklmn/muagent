"""Inline-клавиатуры и текстовые шаблоны для UI."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.time_parser import format_due


def outbound_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отправить", callback_data="outbound:send"),
                InlineKeyboardButton(text="Отмена", callback_data="outbound:cancel"),
            ]
        ]
    )


def memory_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    text = "Выключить память" if enabled else "Включить память"
    action = "off" if enabled else "on"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"memory:{action}")]]
    )


def memory_panel_text(enabled: bool) -> str:
    state = "включена" if enabled else "выключена"
    return (
        f"память сейчас: {state}.\n\n"
        "если включить, я смогу запоминать факты, вспоминать их в business-чатах "
        "и использовать для задач вроде «напиши моему начальнику…».\n\n"
        "если выключить, новые факты записывать не буду."
    )


def task_done_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Готово", callback_data=f"task:done:{task_id}")]]
    )


BOT_BRAND = "Oblivion Assistant"


def disclaimer_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    text = "Выключить подпись" if enabled else "Включить подпись"
    action = "off" if enabled else "on"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"disclaimer:{action}")]]
    )


def disclaimer_panel_text(enabled: bool) -> str:
    state = "включена" if enabled else "выключена"
    return (
        f"подпись в business-ответах сейчас: {state}.\n\n"
        "если включить — каждый ответ контакту будет содержать строку "
        f"«🤖 {BOT_BRAND}» в конце. контакты понимают что отвечает ai, "
        "плюс видят бренд.\n\n"
        "если выключить — отвечаю молча от имени владельца (по умолчанию)."
    )


def sign_business_reply(text: str) -> str:
    """Добавить фирменную подпись к ответу в business-чате."""
    return f"{text}\n\n🤖 {BOT_BRAND}"


def network_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    text = "Выключить интернет" if enabled else "Включить интернет"
    action = "off" if enabled else "on"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"network:{action}")]]
    )


def network_panel_text(enabled: bool) -> str:
    state = "включён" if enabled else "выключен"
    return (
        f"интернет-доступ сейчас: {state}.\n\n"
        "разрешает скиллам ходить в интернет — web search, новости, "
        "погода, курсы валют через специалист-боты (swarm).\n\n"
        "запросы и ответы проходят через telegram-сервера между ботами. "
        "имя владельца, identity и контакты НЕ передаются — только сам запрос."
    )


def task_fallback_text(
    event: str,
    task: dict | None = None,
    points: int | None = None,
) -> str:
    """Резервный текст когда LLM-microcopy (task_voice) упал."""
    if event == "created" and task:
        return (
            f"✅ поставил\n"
            f"📌 {task['title']}\n"
            f"⏰ {format_due(task.get('due_at'))}"
        )
    if event == "reminder" and task:
        return f"🔔 {task['title']}\nвремя пришло."
    if event == "completed" and task:
        return f"✅ закрыл #{task['id']}. +1 очко, всего {points}."
    if event == "list_empty":
        return "дел нет. редкое состояние, почти подозрительно."
    return "готово."
