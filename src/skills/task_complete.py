name = "task_complete"
description = (
    "закрыть задачу по её номеру. используй когда владелец говорит "
    "'готово N', 'закрой задачу N', или явно подтверждает выполнение конкретной задачи."
)
schema = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "integer",
            "description": "номер задачи (id из task_list или из напоминания)",
        }
    },
    "required": ["task_id"],
    "additionalProperties": False,
}
reads = []
writes = ["tasks"]
external_network = False


async def handle(args, ctx):
    task_id = args.get("task_id")
    if not isinstance(task_id, int):
        return {"ok": False, "error": "task_id_required"}

    task = ctx.db.complete_task(ctx.owner_id, task_id)
    if not task:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}

    points = int(ctx.db.get_setting(ctx.owner_id, "task_points", 0) or 0) + 1
    ctx.db.save_settings(ctx.owner_id, task_points=points)
    return {
        "ok": True,
        "task_id": task["id"],
        "title": task["title"],
        "points": points,
    }
