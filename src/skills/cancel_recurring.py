"""Отменить повторяющуюся задачу по её id."""

name = "cancel_recurring"
description = (
    "отключить повторяющуюся подписку по её id. "
    "вызывай когда владелец говорит «не присылай больше новости по AI», "
    "«отмени утреннюю сводку», «убери digest #N»."
)
schema = {
    "type": "object",
    "properties": {
        "job_id": {
            "type": "integer",
            "description": "id повторяющейся задачи (из list_recurring)",
        },
    },
    "required": ["job_id"],
    "additionalProperties": False,
}
reads = []
writes = ["settings"]
external_network = False


async def handle(args, ctx):
    job_id = args.get("job_id")
    if not isinstance(job_id, int):
        return {"ok": False, "error": "job_id_required"}

    removed = ctx.db.disable_recurring_job(ctx.owner_id, job_id)
    if not removed:
        return {"ok": False, "error": "job_not_found_or_already_disabled", "job_id": job_id}

    return {"ok": True, "job_id": job_id}
