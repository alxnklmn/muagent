"""Обработчик business_message — отвечает от имени владельца в его Business-чатах."""

from aiogram import F
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import Message

from core import MAX_HISTORY, bot, dp, log
from db import db
from prompting import build_business_system_prompt, build_status_reminder
from services.llm_runner import run_llm_with_tools
from services.outbound import save_business_contact
from services.thinking import thinking
from states import STATE_READY
from ui import sign_business_reply


@dp.business_message(F.text)
async def on_business_message(message: Message) -> None:
    if not message.from_user or not message.text:
        return

    bc_id = message.business_connection_id
    if not bc_id:
        return  # вне business-контекста — не наш случай

    # 1. находим владельца этого business-подключения
    found = db.find_owner_by_business_connection(bc_id)
    if not found:
        log.warning("no owner found for business_connection_id=%s", bc_id)
        return
    owner_id, owner_record = found

    # 2. КРИТИЧНО: Telegram Business доставляет ОБА направления —
    # и от контакта (нам нужно), и от самого владельца (не нужно). фильтруем.
    if message.from_user.id == owner_id:
        log.debug("skip outgoing business message from owner %d", owner_id)
        return

    # 3. и совсем перестраховка: игнор сообщений от ботов в business-чате
    if message.from_user.is_bot:
        log.debug("skip business message from bot %d", message.from_user.id)
        return

    # дальше user_id — это контакт, не владелец
    user_id = message.from_user.id
    save_business_contact(owner_id, message, bc_id)

    if owner_record.get("state") != STATE_READY:
        log.info(
            "owner %d in state=%s — отвечаю с дефолтным промптом",
            owner_id, owner_record.get("state"),
        )
        owner_id_for_prompt: int | None = None
    else:
        owner_id_for_prompt = owner_id

    # contact_id для prompt — это chat.id (так мы сохраняем контакты)
    system_prompt = build_business_system_prompt(
        owner_id_for_prompt,
        contact_id=message.chat.id if owner_id_for_prompt else None,
    )

    history = db.get_chat_history(user_id)
    history.append({"role": "user", "content": message.text})

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages += history[-MAX_HISTORY:]

    # ВАЖНО: если у владельца активен статус — инжектим напоминание ВТОРЫМ
    # system-сообщением прямо перед user-message. LLM обращает больше внимания
    # на инструкции ближайшие к user query.
    status_reminder = build_status_reminder(
        owner_id_for_prompt,
        contact_id=message.chat.id if owner_id_for_prompt else None,
    )
    if status_reminder and messages and messages[-1].get("role") == "user":
        # вставляем перед последним user-сообщением
        last_user = messages.pop()
        messages.append({"role": "system", "content": status_reminder})
        messages.append(last_user)

    # пока LLM думает: постоянный typing-индикатор. без placeholder-эмодзи —
    # контакту в Business не нужно видеть «🤔» от владельца.
    async with thinking(message.chat.id, business_connection_id=bc_id):
        try:
            reply = await run_llm_with_tools(
                messages=messages,
                owner_id=owner_id_for_prompt,
                source="business",
                temperature=0.7,
            )
        except Exception:
            log.exception("llm call failed")
            return

    if not reply:
        log.warning("empty reply from llm; skipping")
        return

    history.append({"role": "assistant", "content": reply})
    db.set_chat_history(user_id, history[-MAX_HISTORY:])

    # фирменная подпись «🤖 Oblivion Assistant» в конце каждого ответа,
    # если владелец включил её через /disclaimer
    outgoing_text = reply
    if owner_id_for_prompt and db.get_setting(owner_id, "disclaimer", False):
        outgoing_text = sign_business_reply(reply)

    try:
        await bot.send_message(
            chat_id=message.chat.id,
            text=outgoing_text,
            business_connection_id=bc_id,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "business_peer_invalid" in msg or "business_peer_usage_missing" in msg:
            log.warning(
                "cannot reply in business chat (peer excluded or no business access): "
                "owner=%d contact=%d — %s",
                owner_id, message.chat.id, e,
            )
        elif "chat not found" in msg:
            log.warning("chat not found: owner=%d contact=%d", owner_id, message.chat.id)
        else:
            log.warning("telegram bad request on business reply: %s", e)
    except TelegramForbiddenError as e:
        log.warning(
            "forbidden to send business reply (owner=%d contact=%d): %s",
            owner_id, message.chat.id, e,
        )
    except TelegramRetryAfter as e:
        log.warning("rate limited on business reply: retry after %ds", e.retry_after)
    except (TelegramNetworkError, TelegramServerError) as e:
        log.warning("telegram network/server error on business reply: %s", e)
    except Exception:
        log.exception("unexpected error on business reply (owner=%d)", owner_id)
