"""Owner DM handler: онбординг + post-onboarding chat с tools."""

from aiogram import F
from aiogram.types import Message

from core import LLM_MODEL, MAX_HISTORY, MAX_ONBOARDING_HISTORY, bot, dp, llm, log
from db import db
from parsers import (
    parse_memory_toggle,
    parse_outbound_confirmation,
    parse_status_clear,
    parse_status_command,
)
from prompting import build_owner_system_prompt
from services.llm_runner import run_llm_with_tools
from services.onboarding import ONBOARDING_DONE_REPLY, run_onboarding


HELP_TEXT = """🌑 Oblivion Assistant — что умею

— Команды
/autoreply — автоответы в business (вкл/выкл)
/memory — управление памятью (вкл/выкл)
/network — интернет через Рой (вкл/выкл)
/disclaimer — подпись «🤖 Oblivion Assistant» в business
/help — это сообщение

— Естественным языком (без команд)

память:
• «запомни — артём мой партнёр»
• «кто такой артём?»
• «забудь про X»

задачи:
• «напомни через час купить молока»
• «что у меня по делам?»
• «готово 5» (закрыть задачу №5)

статус (для business-чатов):
• «я в лесу на неделю»
• «уехал из страны на месяц»
• «сплю до утра»
• «вернулся»

расписание:
• «каждый день в 9 утра присылай новости про AI»
• «отмени утреннюю сводку»

интернет (после /network):
• «найди статью про X»
• «свежие новости про крипту»

отправка контактам:
• «напиши боссу что я опоздаю»
→ я готовлю draft → ты подтверждаешь кнопкой

контакты:
• «@masha — моя девушка»
• «с боссом всегда официально»

просто пиши как удобно — я разберу что нужно."""
from services.intents import classify_status_intent
from services.outbound import send_pending_outbound
from services.summarize import compress_owner_chat_if_needed, get_chat_summary
from services.thinking import cleanup_placeholder, deliver_reply, thinking
from skills.registry import SkillContext, call_skill
from states import STATE_AWAITING_IDENTITY, STATE_AWAITING_NAME, STATE_READY
from ui import (
    autoreply_keyboard,
    autoreply_panel_text,
    disclaimer_keyboard,
    disclaimer_panel_text,
    memory_keyboard,
    memory_panel_text,
    network_keyboard,
    network_panel_text,
    outbound_confirm_keyboard,
)


@dp.message(F.chat.type == "private", F.text, ~F.from_user.is_bot)
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

    if text == "/memory":
        enabled = db.get_setting(owner_id, "memory_consent", False)
        await message.answer(
            memory_panel_text(enabled),
            reply_markup=memory_keyboard(enabled),
        )
        return

    if text == "/disclaimer":
        enabled = db.get_setting(owner_id, "disclaimer", False)
        await message.answer(
            disclaimer_panel_text(enabled),
            reply_markup=disclaimer_keyboard(enabled),
        )
        return

    if text == "/network":
        enabled = db.get_setting(owner_id, "external_network_consent", False)
        await message.answer(
            network_panel_text(enabled),
            reply_markup=network_keyboard(enabled),
        )
        return

    if text == "/autoreply":
        enabled = db.get_setting(owner_id, "business_auto_reply", False)
        await message.answer(
            autoreply_panel_text(enabled),
            reply_markup=autoreply_keyboard(enabled),
        )
        return

    if text in ("/help", "/start"):
        await message.answer(HELP_TEXT)
        return

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

        if name := result.get("extracted_name"):
            db.save_owner(owner_id, name=name)

        if narrative := result.get("narrative"):
            db.save_identity(owner_id, narrative)

        history = owner.get("onboarding_history", [])
        history.append({"role": "user", "content": text})
        reply = (
            ONBOARDING_DONE_REPLY
            if result.get("done")
            else (result.get("reply") or "").strip()
        )
        if reply:
            history.append({"role": "assistant", "content": reply})
        history = history[-MAX_ONBOARDING_HISTORY:]
        db.save_owner(owner_id, onboarding_history=history)

        if result.get("done"):
            db.set_owner_state(owner_id, STATE_READY)
            log.info("owner %d onboarding complete", owner_id)

        if reply:
            await message.answer(reply)
        return

    if state == STATE_READY:
        # быстрые pre-фильтры до LLM:

        # 1. подтверждение draft текстом «да/нет», если есть pending_outbound
        if owner.get("pending_outbound"):
            confirmation = parse_outbound_confirmation(text)
            if confirmation is True:
                # send_pending_outbound сам ловит все исключения и возвращает
                # понятное сообщение пользователю — не нужно второго try
                reply = await send_pending_outbound(owner_id)
                await message.answer(reply)
                return
            if confirmation is False:
                db.save_owner(owner_id, pending_outbound=None)
                await message.answer("отменил.")
                return

        # 2. natural-language memory toggle через regex (cheap, без LLM)
        if (memory_toggle := parse_memory_toggle(text)) is not None:
            db.save_settings(owner_id, memory_consent=memory_toggle)
            if memory_toggle:
                await message.answer("память включена. теперь могу запоминать факты.")
            else:
                await message.answer("память выключена. новые факты записывать не буду.")
            return

        # 2.5. set_status / clear_status через regex
        # LLM упорно не зовёт set_status даже с явным промптом, поэтому
        # самые частые формулировки ловим detеrministически.
        if parse_status_clear(text):
            ctx = SkillContext(
                owner_id=owner_id, source="dm", db=db,
                llm=llm, llm_model=LLM_MODEL, bot=bot,
            )
            result = await call_skill("clear_status", {}, ctx)
            if result.get("was_active"):
                await message.answer("✅ статус снят. отвечаю обычно.")
            else:
                await message.answer("статуса и так не было.")
            return

        async def _apply_status(status_args: dict) -> None:
            """Вызвать set_status с переданными args, ответить владельцу."""
            ctx = SkillContext(
                owner_id=owner_id, source="dm", db=db,
                llm=llm, llm_model=LLM_MODEL, bot=bot,
            )
            result = await call_skill("set_status", status_args, ctx)
            if result.get("ok"):
                duration = ""
                if "hours" in status_args and status_args["hours"]:
                    duration = f" на {status_args['hours']}ч"
                elif "days" in status_args and status_args["days"]:
                    duration = f" на {status_args['days']}д"
                scope_part = ""
                if status_args.get("scopes"):
                    scope_part = f"\nпоказываю только: {', '.join(status_args['scopes'])}"
                await message.answer(
                    f"✅ статус: «{status_args['text']}»{duration}{scope_part}\n\n"
                    "буду упоминать в business-чатах. скажи «вернулся» чтобы снять раньше."
                )
            else:
                await message.answer(f"не получилось поставить статус: {result}")

        if (status_args := parse_status_command(text)) is not None:
            await _apply_status(status_args)
            return

        # 2.6. fallback — LLM-классификатор намерений. ловит широкий хвост фраз
        # которые regex не предусмотрел: «я в лесу», «уехал из страны», «на даче» и т.п.
        # один маленький JSON-вызов без tools — быстрее и надёжнее главного LLM-passа.
        try:
            classified = await classify_status_intent(text)
        except Exception:
            log.exception("status intent classifier failed")
            classified = None

        if classified and classified.get("is_status"):
            status_text = (classified.get("status_text") or "").strip()
            if status_text:
                args: dict = {"text": status_text}
                if classified.get("hours"):
                    args["hours"] = int(classified["hours"])
                if classified.get("days"):
                    args["days"] = int(classified["days"])
                scopes = classified.get("scopes")
                if scopes and isinstance(scopes, list):
                    args["scopes"] = [str(s) for s in scopes if s]
                await _apply_status(args)
                return

        # 3. основной путь — единый LLM-pass со всеми tools.
        # перед сборкой контекста — если история переросла порог, пожимаем старую часть.
        try:
            await compress_owner_chat_if_needed(owner_id)
        except Exception:
            log.exception("compression check failed (non-fatal)")

        sys_prompt = build_owner_system_prompt(owner_id)
        history = db.get_owner_chat(owner_id)
        history.append({"role": "user", "content": text})

        # сборка messages: outer system + (опц.) summary прошлого + recent history
        messages = [{"role": "system", "content": sys_prompt}]
        prior_summary = get_chat_summary(owner_id)
        if prior_summary:
            messages.append({
                "role": "system",
                "content": f"## контекст из предыдущих разговоров (сжато):\n{prior_summary}",
            })
        messages += history[-MAX_HISTORY:]

        # пока LLM думает: эмодзи-плейсхолдер + постоянный typing-индикатор.
        # placeholder также пробрасываем в SkillContext — скиллы swarm используют его
        # чтобы показать «🐝 спрашиваю Рой...» пока специалист-бот думает.
        async with thinking(message.chat.id, show_placeholder=True) as placeholder:
            try:
                reply = await run_llm_with_tools(
                    messages=messages,
                    owner_id=owner_id,
                    source="dm",
                    temperature=0.6,
                    progress_message=placeholder,
                )
            except Exception:
                log.exception("owner chat LLM failed")
                await deliver_reply(
                    chat_id=message.chat.id,
                    text="что-то отвалилось. секунду.",
                    placeholder=placeholder,
                )
                return

        if not reply:
            log.warning("empty reply from owner-mode LLM")
            await cleanup_placeholder(placeholder)
            return

        history.append({"role": "assistant", "content": reply})
        db.set_owner_chat(owner_id, history[-MAX_HISTORY:])

        # если send_outbound поставил pending — добавляем подтверждение
        owner_after = db.get_owner(owner_id) or {}
        keyboard = (
            outbound_confirm_keyboard()
            if owner_after.get("pending_outbound")
            else None
        )

        await deliver_reply(
            chat_id=message.chat.id,
            text=reply,
            placeholder=placeholder,
            reply_markup=keyboard,
        )
        return

    log.info("owner %d wrote in unknown state=%s", owner_id, state)
