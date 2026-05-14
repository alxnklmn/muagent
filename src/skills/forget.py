name = "forget"
description = "физически удалить сохранённые факты по теме, имени или фрагменту"
schema = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "тема, имя или фрагмент факта, который нужно удалить",
        }
    },
    "required": ["target"],
    "additionalProperties": False,
}
reads = ["facts"]
writes = ["facts"]
external_network = False


async def handle(args, ctx):
    target = (args.get("target") or "").strip()
    if not target:
        return {"ok": False, "error": "target_required"}

    deleted = ctx.db.forget_facts(ctx.owner_id, target)
    return {"ok": True, "target": target, "deleted": deleted}
