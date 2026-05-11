import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import BusinessConnection, Message
from dotenv import load_dotenv
from openai import AsyncOpenAI

from db import db


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat-v3.1")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MAX_HISTORY = 40
MAX_ONBOARDING_HISTORY = 20

SYSTEM_PROMPT = (
    Path(__file__).resolve().parent / "prompts" / "system.md"
).read_text(encoding="utf-8")

OWNER_PROMPT_TEMPLATE = (
    Path(__file__).resolve().parent / "prompts" / "owner.md"
).read_text(encoding="utf-8")


def build_owner_system_prompt(owner_id: int) -> str:
    owner = db.get_owner(owner_id) or {}
    name = owner.get("name") or "(имя неизвестно)"
    identity = db.get_identity(owner_id) or "(портрет ещё не собран)"
    return OWNER_PROMPT_TEMPLATE.format(name=name, identity=identity)

# ---------- onboarding states ----------

STATE_AWAITING_NAME = "awaiting_name"
STATE_AWAITING_IDENTITY = "awaiting_identity"
STATE_READY = "ready"

GREETING = (
    "привет. я Oblivion Assistant.\n\n"
    "буду отвечать в твоих чатах от твоего имени — но пока ничего о тебе "
    "не знаю и поэтому молчу.\n\n"
    "для начала: как тебя называть?"
)

ONBOARDING_SYSTEM_TEMPLATE = """ты — Oblivion Assistant, в режиме первичной настройки с владельцем.

задача: собрать минимальную identity владельца, чтобы потом отвечать в его чатах от его имени и звучать как он.

веди короткий, живой диалог. правила речи:
- lowercase. коротко. без эмодзи. без «конечно» / «с удовольствием» / «буду рад».
- задавай по одному вопросу за раз, не дави списком уточнений.
- если владелец сам начал рассказывать — слушай и не перебивай.
- если владелец задаёт вопрос тебе (вроде «что ты можешь») — отвечай по делу 1-2 предложениями, потом мягко возвращай к настройке.
- ориентир: 2-4 коротких обмена достаточно, чтобы получить базовый портрет.

что входит в базовый портрет:
- имя (как обращаться)
- чем занят (работа, проекты)
- как обычно общается с людьми (тон, длина сообщений, на ты или на вы, мат/эмодзи или нет)
- что важно знать про контекст жизни (опционально, если сам скажет)

текущий контекст:
- предполагаемое имя владельца: {name}
- что владелец уже рассказал в прошлых сообщениях (не повторяй те же вопросы): {drafts}

ответ строго в формате JSON, без markdown-обёрток:
{{
  "reply": "что отправить владельцу сейчас",
  "extracted_name": "короткое имя для обращения (если в текущем или прошлом сообщении явно сказал) или null",
  "narrative": "если уже достаточно инфы — портрет владельца от 3-го лица 100-300 слов: имя, занятие, стиль общения, ключевой контекст. иначе null",
  "done": true_или_false
}}

ставь done=true когда narrative заполнен и можно завершать настройку. в reply при done=true коротко скажи владельцу что начинаешь работать."""


def build_onboarding_system(name: str | None, drafts: list[str]) -> str:
    return ONBOARDING_SYSTEM_TEMPLATE.format(
        name=name or "(пока неизвестно)",
        drafts=json.dumps(drafts, ensure_ascii=False) if drafts else "[]",
    )


# ---------- aiogram + LLM setup ----------

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("oblivion")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
llm = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


# ---------- business connection lifecycle ----------

@dp.business_connection()
async def on_business_connection(connection: BusinessConnection) -> None:
    owner_id = connection.user.id
    log.info(
        "business_connection: owner=%d enabled=%s id=%s",
        owner_id, connection.is_enabled, connection.id,
    )

    if connection.is_enabled:
        existing = db.get_owner(owner_id)
        rights = connection.rights
        can_reply = bool(rights and getattr(rights, "can_reply", False))
        db.save_owner(
            owner_id,
            business_connection_id=connection.id,
            can_reply=can_reply,
        )
        if not existing:
            db.set_owner_state(owner_id, STATE_AWAITING_NAME)
            try:
                await bot.send_message(chat_id=owner_id, text=GREETING)
            except Exception:
                log.exception("failed to send greeting DM to owner %d", owner_id)
        else:
            log.info("owner %d reconnected; not resending greeting", owner_id)
    else:
        log.info("connection disabled by owner %d", owner_id)
        db.save_owner(owner_id, can_reply=False)


# ---------- onboarding via LLM ----------

async def run_onboarding(owner: dict, message_text: str) -> dict:
    """Один шаг диалога настройки. Возвращает {reply, extracted_name, narrative, done}."""
    name = owner.get("name")
    drafts = owner.get("raw_identity_drafts", [])
    history = list(owner.get("onboarding_history", []))
    history.append({"role": "user", "content": message_text})

    sys_prompt = build_onboarding_system(name, drafts)
    messages = [{"role": "system", "content": sys_prompt}] + history[-MAX_ONBOARDING_HISTORY:]

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.5,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "{}").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("invalid JSON from onboarding LLM: %r", raw[:300])
        return {
            "reply": "что-то я ответил мусором. напиши ещё раз.",
            "extracted_name": None,
            "narrative": None,
            "done": False,
        }


# ---------- owner DM handler ----------

@dp.message(F.chat.type == "private", F.text)
async def on_owner_dm(message: Message) -> None:
    if not message.from_user or not message.text:
        return

    owner_id = message.from_user.id
    owner = db.get_owner(owner_id)
    if not owner:
        log.info("DM from non-owner %d — ignoring", owner_id)
        return

    state = owner.get("state")
    text = message.text.strip()

    if state in (STATE_AWAITING_NAME, STATE_AWAITING_IDENTITY):
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass

        try:
            result = await run_onboarding(owner, text)
        except Exception:
            log.exception("onboarding failed for owner %d", owner_id)
            await message.answer("что-то отвалилось у меня внутри. попробуй ещё раз.")
            return

        # apply results
        if name := result.get("extracted_name"):
            db.save_owner(owner_id, name=name)

        if narrative := result.get("narrative"):
            db.save_identity(owner_id, narrative)

        # update onboarding history (append both turns)
        history = owner.get("onboarding_history", [])
        history.append({"role": "user", "content": text})
        reply = (result.get("reply") or "").strip()
        if reply:
            history.append({"role": "assistant", "content": reply})
        history = history[-MAX_ONBOARDING_HISTORY:]
        db.save_owner(owner_id, onboarding_history=history)

        # state transition
        if result.get("done"):
            db.set_owner_state(owner_id, STATE_READY)
            log.info("owner %d onboarding complete", owner_id)

        if reply:
            await message.answer(reply)
        return

    if state == STATE_READY:
        # owner-mode chat: бот = ассистент владельца, идёт обычный диалог
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass

        sys_prompt = build_owner_system_prompt(owner_id)
        history = db.get_owner_chat(owner_id)
        history.append({"role": "user", "content": text})

        messages = [{"role": "system", "content": sys_prompt}] + history[-MAX_HISTORY:]

        try:
            resp = await llm.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.6,
            )
            reply = (resp.choices[0].message.content or "").strip()
        except Exception:
            log.exception("owner chat LLM failed")
            await message.answer("что-то отвалилось. секунду.")
            return

        if not reply:
            log.warning("empty reply from owner-mode LLM")
            return

        history.append({"role": "assistant", "content": reply})
        db.set_owner_chat(owner_id, history[-MAX_HISTORY:])

        await message.answer(reply)
        return

    log.info("owner %d wrote in unknown state=%s", owner_id, state)


# ---------- system prompt assembly ----------

def build_business_system_prompt(owner_id: int | None) -> str:
    """База + identity владельца, если есть."""
    parts = [SYSTEM_PROMPT]
    if owner_id is None:
        return SYSTEM_PROMPT

    owner = db.get_owner(owner_id) or {}
    name = owner.get("name")
    identity = db.get_identity(owner_id)

    if name or identity:
        block = ["---", "контекст про владельца, от чьего имени ты сейчас пишешь."]
        if name:
            block.append(f"имя: {name}")
        if identity:
            block.append("")
            block.append(identity)
        block.append("")
        block.append(
            "важно: identity выше — это реальный стиль владельца. "
            "она приоритетнее общих правил voice & tone, если они противоречат. "
            "пример: если в identity сказано «использует эмодзи» — используй, "
            "даже если по умолчанию правило «без эмодзи»."
        )
        parts.append("\n".join(block))

    return "\n\n".join(parts)


# ---------- business message handler ----------

@dp.business_message(F.text)
async def on_business_message(message: Message) -> None:
    if not message.from_user or not message.text:
        return

    user_id = message.from_user.id
    bc_id = message.business_connection_id

    # найдём владельца по business_connection_id
    owner_id: int | None = None
    if bc_id:
        found = db.find_owner_by_business_connection(bc_id)
        if found:
            owner_id, owner_record = found
            if owner_record.get("state") != STATE_READY:
                log.info(
                    "owner %d in state=%s — отвечаю с дефолтным промптом",
                    owner_id, owner_record.get("state"),
                )
                owner_id = None  # пока не готов → без identity
        else:
            log.warning("no owner found for business_connection_id=%s", bc_id)

    try:
        await bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing",
            business_connection_id=bc_id,
        )
    except Exception as e:
        log.warning("send_chat_action failed: %s", e)

    system_prompt = build_business_system_prompt(owner_id)

    history = db.get_chat_history(user_id)
    history.append({"role": "user", "content": message.text})

    messages = [{"role": "system", "content": system_prompt}] + history[-MAX_HISTORY:]

    try:
        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.7,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception:
        log.exception("llm call failed")
        return

    if not reply:
        log.warning("empty reply from llm; skipping")
        return

    history.append({"role": "assistant", "content": reply})
    db.set_chat_history(user_id, history[-MAX_HISTORY:])

    await bot.send_message(
        chat_id=message.chat.id,
        text=reply,
        business_connection_id=bc_id,
    )


# ---------- main ----------

async def main() -> None:
    me = await bot.get_me()
    log.info("oblivion online as @%s (id=%d)", me.username, me.id)
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
