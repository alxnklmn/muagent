name = "remember"
description = "сохранить факт о человеке, теме или контексте владельца"
schema = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": "короткая тема или имя, к которому относится факт",
        },
        "fact": {
            "type": "string",
            "description": "сам факт, который нужно сохранить",
        },
    },
    "required": ["subject", "fact"],
    "additionalProperties": False,
}
reads = []
writes = ["facts"]
external_network = False


async def handle(args, ctx):
    subject = (args.get("subject") or "").strip()
    fact = (args.get("fact") or "").strip()
    if not subject or not fact:
        return {"ok": False, "error": "subject_and_fact_required"}

    # dedup: если точно такой же факт уже есть — не плодим дубль
    existing = ctx.db.find_existing_fact(ctx.owner_id, subject, fact)
    if existing:
        return {
            "ok": True,
            "deduped": True,
            "id": existing["id"],
            "subject": existing["subject"],
            "fact": existing["fact"],
        }

    saved = ctx.db.add_fact(
        owner_id=ctx.owner_id,
        subject=subject,
        fact=fact,
        source=ctx.source,
    )
    return {
        "ok": True,
        "id": saved["id"],
        "subject": saved["subject"],
        "fact": saved["fact"],
    }
