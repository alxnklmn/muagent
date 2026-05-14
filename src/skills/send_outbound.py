"""Подготовка outbound-сообщения контакту.

Скилл НЕ отправляет — он:
1. находит контакта (через facts: «@user — мой начальник», и через contacts)
2. сохраняет pending_outbound в owner record с ГОТОВЫМ текстом
3. возвращает {ok: true, pending_confirmation: true, recipient, draft}

ВАЖНО (изменено в H.6): второй внутренний LLM-вызов УДАЛЁН. Outer LLM в DM
уже видит identity владельца и тэги контакта, поэтому он сам пишет ПОЛНЫЙ
готовый текст в message_text. Скилл просто кладёт этот текст в pending.

DM handler видит pending_confirmation=true и присылает inline-кнопки.
Реальная отправка — в callback handler outbound:send.
"""


name = "send_outbound"
description = (
    "подготовить сообщение для отправки контакту владельца. "
    "вызывай когда владелец просит написать/отправить кому-то конкретное сообщение. "
    "ВАЖНО: в message_text пиши ПОЛНЫЙ ГОТОВЫЙ ТЕКСТ от имени владельца — "
    "уже в его стиле, с учётом identity и relationship с этим контактом. "
    "не передавай инструкции вроде 'представься' — пиши уже само приветствие. "
    "скилл просто положит этот текст в pending без какой-либо обработки."
)
schema = {
    "type": "object",
    "properties": {
        "recipient_query": {
            "type": "string",
            "description": (
                "имя / @username / часть имени для поиска контакта в сохранённых "
                "(например 'masha', '@boss', 'Иванов')"
            ),
        },
        "message_text": {
            "type": "string",
            "description": (
                "ПОЛНЫЙ ГОТОВЫЙ ТЕКСТ сообщения от первого лица владельца. "
                "не пиши инструкции — пиши финальный текст который пойдёт получателю."
            ),
        },
    },
    "required": ["recipient_query", "message_text"],
    "additionalProperties": False,
}
reads = ["facts", "contacts"]
writes = []  # pending_outbound лежит в owner record, не в facts/identity
external_network = False


def _extract_contact_target(facts: list[dict], fallback: str) -> str:
    """Если в фактах есть @username привязанный к recipient_query — берём его."""
    for item in facts:
        subject = item.get("subject") or ""
        if subject.startswith("@"):
            return subject
    for item in facts:
        for value in (item.get("subject") or "", item.get("fact") or ""):
            for token in value.split():
                if token.startswith("@"):
                    return token.strip(".,!?;:")
    return fallback


async def handle(args, ctx):
    recipient_query = (args.get("recipient_query") or "").strip()
    # back-compat: старое имя поля на случай если LLM по инерции передаст message_request
    message_text = (
        args.get("message_text")
        or args.get("message_request")
        or ""
    ).strip()
    if not recipient_query or not message_text:
        return {"ok": False, "error": "recipient_and_message_required"}

    # 1. сначала пробуем через факты — оттуда может прийти @username
    facts = ctx.db.recall_facts(ctx.owner_id, recipient_query)
    contact_target = _extract_contact_target(facts, recipient_query)

    # 2. резолвим в реальный контакт через find_contact
    found = ctx.db.find_contact(ctx.owner_id, contact_target)
    if not found and contact_target != recipient_query:
        # fallback: исходный запрос (вдруг факты увели не туда)
        found = ctx.db.find_contact(ctx.owner_id, recipient_query)

    if not found:
        return {
            "ok": False,
            "error": "contact_not_found",
            "recipient_resolved": contact_target,
            "hint": "контакт должен сначала написать в Business-чат, чтобы я его сохранил",
        }

    contact_id, contact = found
    recipient_label = (
        f"@{contact['username']}"
        if contact.get("username")
        else contact.get("full_name")
    ) or str(contact_id)

    # 3. сохраняем pending — текст уходит КАК ЕСТЬ, без второго LLM-вызова
    owner = ctx.db.get_owner(ctx.owner_id) or {}
    pending = {
        "chat_id": contact.get("chat_id") or contact_id,
        "business_connection_id": (
            contact.get("business_connection_id")
            or owner.get("business_connection_id")
        ),
        "recipient": recipient_label,
        "text": message_text,
    }
    ctx.db.save_owner(ctx.owner_id, pending_outbound=pending)

    return {
        "ok": True,
        "pending_confirmation": True,
        "recipient": recipient_label,
        "draft": message_text,
    }
