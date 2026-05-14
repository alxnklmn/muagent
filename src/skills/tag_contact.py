"""Поставить тэги и описание relationship для контакта.

Используется когда владелец классифицирует собеседника:
«@boss — это мой начальник» / «маша — это девушка» / «иван work и важный».

Теги влияют на:
- scope для status (статус могут видеть только определённые теги)
- тон бота в business-ответах (с work-контактами строже, с family свободнее)
"""


name = "tag_contact"
description = (
    "обновить метаданные контакта владельца: теги, relationship, voice_notes. "
    "используй когда владелец классифицирует/описывает собеседника: "
    "«@masha — моя девушка» / «с боссом всегда официально» / «он любит когда коротко и по делу». "
    "ВСЕ поля кроме contact_query опциональны — передавай только то что хочешь обновить. "
    "контакт ищется по @username, имени или фамилии через find_contact."
)
schema = {
    "type": "object",
    "properties": {
        "contact_query": {
            "type": "string",
            "description": "@username, имя или часть имени для поиска контакта в сохранённых",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "теги: work / family / girlfriend / boss / friend / client и т.п. Добавляются к существующим.",
        },
        "relationship": {
            "type": "string",
            "description": "одна фраза кто это для владельца («начальник по проекту X», «мама»)",
        },
        "voice_notes": {
            "type": "string",
            "description": (
                "короткие заметки КАК говорить с этим контактом. "
                "примеры: «всегда на вы, без шуток», «коротко и по делу», "
                "«по-английски, профессионально», «можно мат, она такая же», "
                "«не упоминать проект X». заменяет старое содержимое."
            ),
        },
    },
    "required": ["contact_query"],
    "additionalProperties": False,
}
reads = ["contacts"]
writes = ["contacts"]
external_network = False


async def handle(args, ctx):
    query = (args.get("contact_query") or "").strip()
    if not query:
        return {"ok": False, "error": "contact_query_required"}

    found = ctx.db.find_contact(ctx.owner_id, query)
    if not found:
        return {
            "ok": False,
            "error": "contact_not_found",
            "query": query,
            "hint": "контакт должен сначала написать в business-чат, чтобы я его сохранил",
        }

    contact_id, contact = found
    tags = args.get("tags")
    relationship = (args.get("relationship") or "").strip()
    voice_notes = args.get("voice_notes")
    if voice_notes is not None:
        voice_notes = voice_notes.strip()

    fields: dict = {}
    if tags is not None:
        # объединяем со старыми, удаляя дубли, сохраняя порядок
        existing = list(contact.get("tags") or [])
        seen = set(existing)
        for tag in tags:
            tag_norm = tag.strip().casefold()
            if tag_norm and tag_norm not in seen:
                existing.append(tag_norm)
                seen.add(tag_norm)
        fields["tags"] = existing
    if relationship:
        fields["relationship"] = relationship
    if voice_notes is not None:
        # пустая строка = очистка voice_notes
        fields["voice_notes"] = voice_notes if voice_notes else None

    if not fields:
        return {"ok": False, "error": "nothing_to_update"}

    ctx.db.save_contact(ctx.owner_id, contact_id, **fields)
    return {
        "ok": True,
        "contact_id": contact_id,
        "name": contact.get("full_name") or contact.get("username"),
        "tags": fields.get("tags", contact.get("tags")),
        "relationship": fields.get("relationship", contact.get("relationship")),
        "voice_notes": fields.get("voice_notes", contact.get("voice_notes")),
    }
