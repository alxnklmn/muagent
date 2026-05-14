"""Один LLM-pass с OpenAI-style tool/function calling.

Это сердце всех LLM-вызовов после E.5.2. LLM сам решает что вызвать через tools,
ядро исполняет skills и возвращает результаты обратно в контекст.
"""

import json

from core import LLM_MODEL, MAX_TOOL_ROUNDS, bot, llm, log
from db import db
from skills.registry import SkillContext, call_skill, openai_tools, parse_tool_arguments


async def run_llm_with_tools(
    messages: list[dict],
    owner_id: int | None,
    source: str,
    temperature: float,
    progress_message: object | None = None,
) -> str:
    working_messages = list(messages)
    tools = openai_tools() if owner_id is not None else []
    calls_seen: list[str] = []  # для дебага: какие скиллы крутились

    for round_idx in range(MAX_TOOL_ROUNDS):
        request = {
            "model": LLM_MODEL,
            "messages": working_messages,
            "temperature": temperature,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"

        resp = await llm.chat.completions.create(**request)
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            return (msg.content or "").strip()

        working_messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments or "{}",
                        },
                    }
                    for tool_call in tool_calls
                ],
            }
        )

        ctx = SkillContext(
            owner_id=owner_id,
            source=source,
            db=db,
            llm=llm,
            llm_model=LLM_MODEL,
            bot=bot,
            progress_message=progress_message,
        )
        for tool_call in tool_calls:
            name = tool_call.function.name
            calls_seen.append(name)
            args = parse_tool_arguments(tool_call.function.arguments)
            result = await call_skill(name, args, ctx)
            working_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    # MAX_TOOL_ROUNDS превышен — модель крутится в цикле tool-calls.
    # tool-call recovery: даём LLM шанс "завершиться" БЕЗ tools, оставив
    # current_messages валидными. инъекция request → "хватит, ответь без tools".
    log.warning(
        "too many tool rounds (source=%s owner=%s skills=%s); forcing close",
        source, owner_id, calls_seen,
    )
    working_messages.append(
        {
            "role": "system",
            "content": (
                "ты вызвал tools слишком много раз. больше tools не вызывай. "
                "коротко ответь владельцу о том, что получилось сделать, "
                "и что не получилось. если ничего внятного не вышло — извинись "
                "одной фразой и предложи переформулировать."
            ),
        }
    )
    try:
        final = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=working_messages,
            temperature=0.4,
            # tool_choice="none" заставляет LLM ответить текстом
            tools=tools if tools else None,
            tool_choice="none" if tools else None,
        )
        return (final.choices[0].message.content or "").strip() or (
            "застрял в цикле. повтори короче."
        )
    except Exception:
        log.exception("force-close llm call failed")
        return "застрял в цикле. повтори короче."
