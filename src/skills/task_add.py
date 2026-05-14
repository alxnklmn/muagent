from services.time_parser import clean_task_title, format_due, parse_due_text


name = "task_add"
description = (
    "создать задачу или напоминание. due_text — натуральное выражение времени "
    "(например 'через 10 минут', 'завтра в 18:00', 'послезавтра'). "
    "оставь пустым если задача без срока. не вставляй в title слово 'напомни'."
)
schema = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "короткое название задачи без вежливых слов",
        },
        "due_text": {
            "type": "string",
            "description": "выражение времени; пустая строка = без срока",
        },
    },
    "required": ["title"],
    "additionalProperties": False,
}
reads = []
writes = ["tasks"]
external_network = False


async def handle(args, ctx):
    title = clean_task_title((args.get("title") or "").strip())
    if not title:
        return {"ok": False, "error": "title_required"}

    due_at = parse_due_text(args.get("due_text"))
    task = ctx.db.add_task(
        owner_id=ctx.owner_id,
        title=title,
        due_at=due_at,
        source=ctx.source,
    )
    return {
        "ok": True,
        "task_id": task["id"],
        "title": task["title"],
        "due_at": task["due_at"],
        "due_human": format_due(task.get("due_at")),
    }
