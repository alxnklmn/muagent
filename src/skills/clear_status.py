"""Снять текущий статус владельца (он вернулся в строй)."""

name = "clear_status"
description = (
    "снять текущий статус владельца. используй когда владелец говорит "
    "«я вернулся», «отмени отпуск», «снял статус», «больше не сплю»."
)
schema = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
reads = []
writes = ["settings"]
external_network = False


async def handle(args, ctx):
    owner = ctx.db.get_owner(ctx.owner_id) or {}
    if not owner.get("status"):
        return {"ok": True, "was_active": False}

    ctx.db.save_owner(ctx.owner_id, status=None)
    return {"ok": True, "was_active": True}
