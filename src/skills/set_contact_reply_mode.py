"""Явно переключить reply_mode для контакта.

Используется когда владелец говорит:
- «с @user всегда сначала спрашивай меня» → mode='draft'
- «с боссом без подтверждений, отвечай сам» → mode='auto'
- «никому из этих не отвечай» → mode='silent' для каждого
"""

name = "set_contact_reply_mode"
description = (
    "переключить режим автоответа для конкретного контакта: "
    "auto (отвечаю сам без подтверждения), "
    "draft (сначала показываю тебе draft и жду подтверждение, дефолт для untagged), "
    "silent (вообще игнорим этого контакта в business). "
    "вызывай когда владелец явно говорит: «с @user сначала спрашивай», "
    "«с боссом без подтверждений», «не отвечай маме», и т.п."
)
schema = {
    "type": "object",
    "properties": {
        "contact_query": {
            "type": "string",
            "description": "@username, имя или часть имени для поиска контакта",
        },
        "mode": {
            "type": "string",
            "enum": ["auto", "draft", "silent"],
            "description": "auto = отвечать сразу, draft = ждать подтверждение, silent = игнорить",
        },
    },
    "required": ["contact_query", "mode"],
    "additionalProperties": False,
}
reads = ["contacts"]
writes = ["contacts"]
external_network = False


async def handle(args, ctx):
    query = (args.get("contact_query") or "").strip()
    mode = (args.get("mode") or "").strip().lower()
    if not query:
        return {"ok": False, "error": "contact_query_required"}
    if mode not in ("auto", "draft", "silent"):
        return {"ok": False, "error": "mode_must_be_auto_draft_or_silent"}

    found = ctx.db.find_contact(ctx.owner_id, query)
    if not found:
        return {"ok": False, "error": "contact_not_found", "query": query}

    contact_id, contact = found
    ctx.db.save_contact(ctx.owner_id, contact_id, reply_mode=mode)
    return {
        "ok": True,
        "contact_id": contact_id,
        "name": contact.get("full_name") or contact.get("username"),
        "mode": mode,
    }
