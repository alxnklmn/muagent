"""Inline-кнопки: memory:on/off, task:done:N, outbound:send/cancel."""

from aiogram import F
from aiogram.types import CallbackQuery

from core import dp, log
from db import db
from services.messaging import task_voice
from services.outbound import send_pending_outbound
from ui import (
    autoreply_enabled_followup,
    autoreply_keyboard,
    autoreply_panel_text,
    disclaimer_keyboard,
    disclaimer_panel_text,
    memory_keyboard,
    memory_panel_text,
    network_keyboard,
    network_panel_text,
)


@dp.callback_query(F.data.startswith("task:done:"))
async def on_task_done_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return

    owner_id = callback.from_user.id
    try:
        task_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("битый id", show_alert=True)
        return

    task = db.complete_task(owner_id, task_id)
    if not task:
        await callback.answer("не нашёл задачу", show_alert=True)
        return

    points = int(db.get_setting(owner_id, "task_points", 0) or 0) + 1
    db.save_settings(owner_id, task_points=points)
    text = await task_voice("completed", task, points)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(text)
    await callback.answer("+1")


@dp.callback_query(F.data.in_({"memory:on", "memory:off"}))
async def on_memory_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return

    owner_id = callback.from_user.id
    enabled = callback.data == "memory:on"
    db.save_settings(owner_id, memory_consent=enabled)

    if callback.message:
        await callback.message.edit_text(
            memory_panel_text(enabled),
            reply_markup=memory_keyboard(enabled),
        )
    await callback.answer("память включена" if enabled else "память выключена")


@dp.callback_query(F.data.in_({"disclaimer:on", "disclaimer:off"}))
async def on_disclaimer_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return

    owner_id = callback.from_user.id
    enabled = callback.data == "disclaimer:on"
    db.save_settings(owner_id, disclaimer=enabled)

    if callback.message:
        await callback.message.edit_text(
            disclaimer_panel_text(enabled),
            reply_markup=disclaimer_keyboard(enabled),
        )
    await callback.answer("дисклеймер включён" if enabled else "дисклеймер выключен")


@dp.callback_query(F.data.in_({"autoreply:on", "autoreply:off"}))
async def on_autoreply_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return

    owner_id = callback.from_user.id
    enabled = callback.data == "autoreply:on"
    db.save_settings(owner_id, business_auto_reply=enabled)

    if callback.message:
        await callback.message.edit_text(
            autoreply_panel_text(enabled),
            reply_markup=autoreply_keyboard(enabled),
        )
        # дополнительное follow-up сообщение когда включили — объясняем как тонко настроить
        if enabled:
            await callback.message.answer(autoreply_enabled_followup())
    await callback.answer("автоответы включены" if enabled else "автоответы выключены")


@dp.callback_query(F.data.in_({"network:on", "network:off"}))
async def on_network_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return

    owner_id = callback.from_user.id
    enabled = callback.data == "network:on"
    db.save_settings(owner_id, external_network_consent=enabled)

    if callback.message:
        await callback.message.edit_text(
            network_panel_text(enabled),
            reply_markup=network_keyboard(enabled),
        )
    await callback.answer("интернет включён" if enabled else "интернет выключен")


@dp.callback_query(F.data.in_({"outbound:send", "outbound:cancel"}))
async def on_outbound_callback(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return

    owner_id = callback.from_user.id
    owner = db.get_owner(owner_id)
    if not owner:
        await callback.answer("не вижу owner state", show_alert=True)
        return

    if callback.data == "outbound:cancel":
        db.save_owner(owner_id, pending_outbound=None)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("отменил")
        return

    # send_pending_outbound сам обрабатывает все ошибки и возвращает
    # человечный текст. передаём дальше владельцу.
    reply = await send_pending_outbound(owner_id)

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(reply)
    # callback.answer лимит 200 символов, обрезаем если что
    await callback.answer(reply[:200])
