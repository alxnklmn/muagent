"""Фоновый scheduler: due-task напоминания + proactive-пинги.

Живёт внутри polling-процесса как create_task. Тикает каждые 15 секунд.
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from core import bot, log
from db import db
from services.messaging import task_voice
from services.time_parser import LOCAL_TZ, format_due
from services.tracks import format_track, pick_track
from states import STATE_READY
from ui import task_done_keyboard


async def task_scheduler() -> None:
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            for task in db.due_tasks(now_iso):
                text = await task_voice("reminder", task)
                await bot.send_message(
                    chat_id=task["owner_id"],
                    text=text,
                    reply_markup=task_done_keyboard(task["id"]),
                )
                db.mark_task_reminded(task["id"])
                db.append_audit_log(
                    task["owner_id"],
                    "todo_reminder",
                    {"task_id": task["id"]},
                    {"ok": True, "title": task["title"]},
                )
            await proactive_tick()
            await recurring_jobs_tick()
            # автоотправка зависших draft-ов > 5 мин
            try:
                from services.draft import auto_send_overdue_drafts
                await auto_send_overdue_drafts()
            except Exception:
                log.exception("auto-send overdue drafts failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("task scheduler tick failed")

        await asyncio.sleep(15)


def _job_is_due(job: dict, now_local: datetime) -> bool:
    """Job должен запуститься если:
    - текущий час:минута == расписанию (с допуском в одну минуту вверх)
    - last_run_at < сегодняшнего времени запуска по локальному tz
    """
    target_time = now_local.replace(
        hour=int(job["hour_local"]),
        minute=int(job["minute_local"]),
        second=0,
        microsecond=0,
    )
    # окно: с target_time до target_time + 5 мин (запас если scheduler пропустил тик)
    if not (target_time <= now_local <= target_time + timedelta(minutes=5)):
        return False

    last = job.get("last_run_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        # если последний run был раньше сегодняшнего target_time — запускаем
        return last_dt < target_time.astimezone(timezone.utc)
    except Exception:
        return True


async def _execute_recurring_job(job: dict) -> None:
    """Выполнить one-shot fire: вызвать соответствующий swarm-skill, отформатировать,
    отправить владельцу в DM, отметить last_run_at."""
    # ленивый импорт чтобы избежать кругового импорта (swarm → core → ...)
    from services.swarm import call_specialist

    owner_id = job["owner_id"]
    kind = job["kind"]
    query = job["query"]

    method = "news" if kind == "news" else "search"
    result = await call_specialist("research", method, {"query": query, "max_results": 5}, timeout=25.0)

    if not result.get("ok"):
        log.warning(
            "recurring job #%d failed: %s",
            job["id"], result.get("error"),
        )
        return

    text = await _format_digest(kind, query, result)
    if not text:
        return

    try:
        await bot.send_message(chat_id=owner_id, text=text)
    except Exception:
        log.exception("failed to deliver recurring digest #%d", job["id"])
        return

    db.mark_recurring_job_run(job["id"])
    db.append_audit_log(
        owner_id,
        "recurring_digest",
        {"job_id": job["id"], "kind": kind, "query": query},
        {"ok": True, "answer_len": len(result.get("answer") or "")},
    )


async def _format_digest(kind: str, query: str, result: dict) -> str:
    """LLM собирает приличный текст digest-а на основе answer + results."""
    answer = result.get("answer") or ""
    items = result.get("results") or []
    items_text = "\n".join(
        f"- {it.get('title', '')} | {it.get('url', '')} | {(it.get('snippet') or '')[:200]}"
        for it in items[:5]
    )
    sys_prompt = (
        "ты — Oblivion Assistant. собираешь утреннюю сводку для владельца. "
        "стиль: lowercase, по делу, 2-4 коротких предложения сводки + 2-3 ссылки. "
        "без 'согласно источникам', без воды.\n\n"
        "формат:\n\n"
        f"{'📰' if kind == 'news' else '🌐'} <тема> — <дата если в новостях>\n\n"
        "<сводка 2-4 предложения, конкретно: цифры, события, имена>\n\n"
        f"{'🗞 свежие материалы:' if kind == 'news' else '📎 источники:'}\n"
        "• <title> — <source/домен>\n"
        "• ...\n\n"
        "source — короткое название издания (CNBC, Habr, ...) или домен без www. и tld.\n"
        "максимум 3 ссылки."
    )

    try:
        from core import LLM_MODEL, llm

        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {
                    "role": "user",
                    "content": (
                        f"тема: {query}\n\n"
                        f"answer от поисковика:\n{answer}\n\n"
                        f"найденные материалы:\n{items_text}"
                    ),
                },
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        log.exception("digest formatting failed")
        # минимальный fallback
        emoji = "📰" if kind == "news" else "🌐"
        lines = [f"{emoji} {query}", "", answer[:500] if answer else "(пусто)"]
        if items:
            lines.append("")
            lines.append("источники:")
            for it in items[:3]:
                lines.append(f"• {it.get('title','')[:80]}")
        return "\n".join(lines)


async def recurring_jobs_tick() -> None:
    """Раз в 15 секунд (как и весь scheduler) — проверяем нет ли due jobs."""
    now_local = datetime.now(LOCAL_TZ)
    jobs = db.list_all_recurring_jobs()
    for job in jobs:
        if not _job_is_due(job, now_local):
            continue
        log.info(
            "firing recurring job #%d for owner %d (%s: %s)",
            job["id"], job["owner_id"], job["kind"], job["query"],
        )
        try:
            await _execute_recurring_job(job)
        except Exception:
            log.exception("recurring job #%d execution failed", job["id"])


def in_quiet_hours(settings: dict) -> bool:
    quiet = settings.get("quiet_hours") or {}
    start = quiet.get("from", "23:00")
    end = quiet.get("to", "09:00")
    now = datetime.now(LOCAL_TZ).time()
    start_t = datetime.strptime(start, "%H:%M").time()
    end_t = datetime.strptime(end, "%H:%M").time()
    if start_t < end_t:
        return start_t <= now < end_t
    return now >= start_t or now < end_t


def proactive_allowed(owner_id: int, kind: str) -> bool:
    settings = db.get_settings(owner_id)
    if not settings.get("proactive_enabled", False):
        return False
    if in_quiet_hours(settings):
        return False

    day_start = datetime.now(LOCAL_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).astimezone(timezone.utc).isoformat()
    budget = int(settings.get("proactive_daily_budget", 2) or 0)
    if db.proactive_count_since(owner_id, day_start) >= budget:
        return False

    last_same = db.last_proactive(owner_id, kind)
    if last_same:
        last_at = datetime.fromisoformat(last_same["created_at"])
        if datetime.now(timezone.utc) - last_at < timedelta(hours=4):
            return False
    return True


async def proactive_message(kind: str, tasks: list[dict]) -> str:
    tasks_text = "\n".join(
        f"- #{task['id']} {task['title']} — {format_due(task.get('due_at'))}"
        for task in tasks[:5]
    )
    prompt = (
        f"event={kind}\n"
        f"open_tasks:\n{tasks_text or '(нет)'}\n\n"
        "напиши короткий proactive ping владельцу. "
        "не будь навязчивым. если задач нет — можно мягко спросить, что сегодня двигаем."
    )
    try:
        from services.messaging import TASK_VOICE_SYSTEM
        from core import llm, LLM_MODEL
        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": TASK_VOICE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or "я тут. если что-то двигаем сегодня — кидай."
    except Exception:
        log.exception("proactive voice failed")
        return "я тут. если что-то двигаем сегодня — кидай."


async def maybe_send_proactive(owner_id: int, kind: str, tasks: list[dict]) -> None:
    if not proactive_allowed(owner_id, kind):
        return
    text = await proactive_message(kind, tasks)
    settings = db.get_settings(owner_id)
    if kind == "daily_checkin" and settings.get("music_enabled", True):
        if random.random() < 0.25:
            track = pick_track("focus")
            text += "\n\nтрек под это:\n" + format_track(track)
    await bot.send_message(chat_id=owner_id, text=text)
    db.add_proactive_log(owner_id, kind, text)


async def proactive_tick() -> None:
    now = datetime.now(LOCAL_TZ)
    for owner_id_text, owner in db.list_owners().items():
        owner_id = int(owner_id_text)
        if owner.get("state") != STATE_READY:
            continue

        tasks = db.list_tasks(owner_id)
        if now.hour in (10, 11) and db.get_setting(
            owner_id,
            "daily_checkin_enabled",
            True,
        ):
            await maybe_send_proactive(owner_id, "daily_checkin", tasks)

        stale = [
            task
            for task in tasks
            if task.get("due_at")
            and datetime.fromisoformat(task["due_at"]).astimezone(LOCAL_TZ) < now
            and task.get("reminded_at")
        ]
        if stale:
            await maybe_send_proactive(owner_id, "stale_task", stale)
