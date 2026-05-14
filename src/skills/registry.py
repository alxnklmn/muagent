import importlib
import inspect
import json
import pkgutil
import re
from dataclasses import dataclass
from types import ModuleType
from typing import Any


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d\s().-]{7,}\d(?!\d)")


@dataclass
class SkillContext:
    owner_id: int
    source: str
    db: Any
    llm: Any = None  # AsyncOpenAI client, опционально (нужен скиллам которые сами зовут LLM)
    llm_model: str = ""
    bot: Any = None  # aiogram Bot, опционально (нужен скиллам которые шлют сообщения)
    progress_message: Any = None  # aiogram Message для edit_text — показать прогресс владельцу


@dataclass
class Skill:
    name: str
    description: str
    schema: dict
    reads: list[str]
    writes: list[str]
    external_network: bool
    module: ModuleType


def mask_pii(value: Any) -> Any:
    if isinstance(value, str):
        value = EMAIL_RE.sub("<email>", value)
        return PHONE_RE.sub("<phone>", value)
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_pii(item) for key, item in value.items()}
    return value


def normalize_schema(schema: dict) -> dict:
    if schema.get("type") == "object":
        return schema

    properties = {}
    required = []
    for key, value in schema.items():
        required.append(key)
        if value is str:
            properties[key] = {"type": "string"}
        elif value is int:
            properties[key] = {"type": "integer"}
        elif value is bool:
            properties[key] = {"type": "boolean"}
        else:
            properties[key] = value

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def load_skills() -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    package = importlib.import_module("skills")
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue

        module = importlib.import_module(f"skills.{info.name}")
        skill = Skill(
            name=module.name,
            description=module.description,
            schema=normalize_schema(module.schema),
            reads=list(getattr(module, "reads", [])),
            writes=list(getattr(module, "writes", [])),
            external_network=bool(getattr(module, "external_network", False)),
            module=module,
        )
        skills[skill.name] = skill
    return skills


SKILLS = load_skills()


def openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": skill.name,
                "description": skill.description,
                "parameters": skill.schema,
            },
        }
        for skill in SKILLS.values()
    ]


def tool_manifest_for_prompt() -> str:
    lines = []
    for skill in SKILLS.values():
        # сжимаем мульти-строчные описания в одну линию для манифеста.
        # полное описание всё равно уходит в JSON schema через openai_tools().
        compact_desc = " ".join(skill.description.split())
        lines.append(
            f"- {skill.name}: {compact_desc}; "
            f"reads={skill.reads}; writes={skill.writes}; "
            f"external_network={str(skill.external_network).lower()}"
        )
    return "\n".join(lines)


async def call_skill(name: str, args: dict, ctx: SkillContext) -> dict:
    skill = SKILLS.get(name)
    if not skill:
        return {"ok": False, "error": f"unknown skill: {name}"}

    if skill.external_network:
        if not ctx.db.get_setting(ctx.owner_id, "external_network_consent", False):
            result = {
                "ok": False,
                "error": "external_network_consent_required",
                "message": "интернет-доступ выключен. владелец должен включить через /network.",
            }
            ctx.db.append_audit_log(ctx.owner_id, name, mask_pii(args), result)
            return result

    if "facts" in skill.writes and not ctx.db.get_setting(
        ctx.owner_id,
        "memory_consent",
        False,
    ):
        result = {
            "ok": False,
            "error": "memory_consent_required",
            "message": "память выключена. владелец должен включить её явно.",
        }
        ctx.db.append_audit_log(ctx.owner_id, name, mask_pii(args), result)
        return result

    try:
        maybe_result = skill.module.handle(args, ctx)
        result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    ctx.db.append_audit_log(ctx.owner_id, name, mask_pii(args), mask_pii(result))
    return result


def parse_tool_arguments(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
