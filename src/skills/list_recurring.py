"""Показать список активных повторяющихся задач владельца."""

name = "list_recurring"
description = (
    "показать все активные повторяющиеся подписки/digest-ы владельца. "
    "вызывай когда владелец спрашивает «какие у меня подписки», "
    "«что ты мне присылаешь регулярно», «какие digest-ы»."
)
schema = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
reads = ["settings"]
writes = []
external_network = False


async def handle(args, ctx):
    jobs = ctx.db.list_recurring_jobs(ctx.owner_id, only_enabled=True)
    return {
        "ok": True,
        "count": len(jobs),
        "jobs": [
            {
                "id": j["id"],
                "kind": j["kind"],
                "query": j["query"],
                "time": f"{j['hour_local']:02d}:{j['minute_local']:02d}",
                "last_run_at": j.get("last_run_at"),
            }
            for j in jobs
        ],
    }
