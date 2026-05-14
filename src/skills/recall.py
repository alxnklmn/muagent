name = "recall"
description = "найти релевантные сохранённые факты по теме, имени или вопросу"
schema = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "тема, имя или вопрос, по которому надо найти факты",
        }
    },
    "required": ["query"],
    "additionalProperties": False,
}
reads = ["facts"]
writes = []
external_network = False


async def handle(args, ctx):
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}

    facts = ctx.db.recall_facts(ctx.owner_id, query)
    return {
        "ok": True,
        "query": query,
        "facts": [
            {
                "id": item["id"],
                "subject": item["subject"],
                "fact": item["fact"],
                "source": item["source"],
                "created_at": item["created_at"],
            }
            for item in facts
        ],
    }
