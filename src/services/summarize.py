"""Rolling-компрессия owner DM-истории.

После N сообщений старая часть пожимается в краткий summary, который
дальше живёт в owner record под ключом `chat_summary` и инжектится в
LLM-контекст отдельным system-сообщением. Это позволяет помнить общий
контекст разговора, не таская в каждый запрос 100 строк истории.
"""

from core import LLM_MODEL, llm, log
from db import db


SUMMARIZE_THRESHOLD = 30  # компрессим когда owner_chat вырос больше этого
SUMMARIZE_BATCH = 20  # сколько самых старых сообщений уходит в summary за один проход
KEEP_RECENT = SUMMARIZE_THRESHOLD - SUMMARIZE_BATCH  # сколько последних оставляем как есть


SUMMARIZE_SYSTEM = """ты — компрессор диалога владельца с ai-ассистентом.

у тебя на входе:
1. предыдущий summary всех старых сообщений (может быть пустой)
2. новый блок старых сообщений, которые надо включить в summary

задача: вернуть ОБНОВЛЁННЫЙ summary, объединяющий обе части.

формат:
- 100-300 слов
- lowercase
- сжатый нарратив, не список
- сохраняй: имена, факты, решения, договорённости, темы, эмоциональный фон
- НЕ сохраняй: вежливые формулировки, пустые реплики, мелкие подтверждения
- если новая инфа противоречит старой — оставь новую
- без вступлений типа "владелец и ассистент обсуждали..." — сразу к делу

верни ТОЛЬКО текст summary, без markdown-обёрток."""


async def _summarize_with_prior(prior_summary: str, old_msgs: list[dict]) -> str:
    """Один LLM-вызов: prior + new old_msgs → new summary."""
    convo_lines = []
    for m in old_msgs:
        role = m.get("role", "?")
        content = m.get("content", "")
        if content:
            convo_lines.append(f"{role}: {content}")
    convo = "\n".join(convo_lines)

    user_prompt = (
        "## предыдущий summary:\n"
        f"{prior_summary or '(пусто, это первая компрессия)'}\n\n"
        "## новые старые сообщения:\n"
        f"{convo}"
    )

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SUMMARIZE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    return (resp.choices[0].message.content or "").strip()


async def compress_owner_chat_if_needed(owner_id: int) -> bool:
    """Если owner_chat превысил порог — суммаризируем старую часть.

    Returns True если компрессия произошла.
    """
    history = db.get_owner_chat(owner_id)
    if len(history) <= SUMMARIZE_THRESHOLD:
        return False

    old_msgs = history[:SUMMARIZE_BATCH]
    fresh_msgs = history[SUMMARIZE_BATCH:]

    owner = db.get_owner(owner_id) or {}
    prior_summary = owner.get("chat_summary", "") or ""

    try:
        new_summary = await _summarize_with_prior(prior_summary, old_msgs)
    except Exception:
        log.exception("compression failed for owner %d — leaving history as is", owner_id)
        return False

    if not new_summary:
        log.warning("empty summary from llm for owner %d — leaving history", owner_id)
        return False

    db.save_owner(owner_id, chat_summary=new_summary)
    db.set_owner_chat(owner_id, fresh_msgs)
    log.info(
        "compressed owner_chat %d: %d→%d msgs, summary %d chars",
        owner_id, len(history), len(fresh_msgs), len(new_summary),
    )
    return True


def get_chat_summary(owner_id: int) -> str | None:
    """Получить текущий summary для инжекции в LLM-контекст."""
    owner = db.get_owner(owner_id) or {}
    summary = owner.get("chat_summary")
    return summary if summary else None
