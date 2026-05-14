from services.time_parser import format_due


name = "task_list"
description = (
    "вернуть открытые задачи владельца. используй когда владелец спрашивает "
    "что у него по делам, какие задачи, что не сделано."
)
schema = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
reads = ["tasks"]
writes = []
external_network = False


async def handle(args, ctx):
    tasks = ctx.db.list_tasks(ctx.owner_id)
    return {
        "ok": True,
        "count": len(tasks),
        "tasks": [
            {
                "id": task["id"],
                "title": task["title"],
                "due_at": task.get("due_at"),
                "due_human": format_due(task.get("due_at")),
            }
            for task in tasks
        ],
    }
