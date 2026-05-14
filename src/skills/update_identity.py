name = "update_identity"
description = (
    "добавить новую информацию в портрет (identity) владельца. "
    "используй когда владелец делится тем что должно остаться надолго: "
    "новый проект, важный контекст жизни, изменение стиля общения, новая роль. "
    "это апдейт собственного портрета, не отдельный факт о ком-то другом."
)
schema = {
    "type": "object",
    "properties": {
        "addition": {
            "type": "string",
            "description": "что добавить в портрет, одной-двумя фразами от третьего лица",
        }
    },
    "required": ["addition"],
    "additionalProperties": False,
}
reads = ["identity"]
writes = ["identity"]
external_network = False


async def handle(args, ctx):
    addition = (args.get("addition") or "").strip()
    if not addition:
        return {"ok": False, "error": "addition_required"}

    current = (ctx.db.get_identity(ctx.owner_id) or "").strip()
    if current:
        updated = f"{current}\n\n— {addition}"
    else:
        updated = addition

    ctx.db.save_identity(ctx.owner_id, updated)
    return {"ok": True, "addition": addition, "identity_length": len(updated)}
