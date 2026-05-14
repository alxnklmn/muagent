"""Video specialist bot: скачивает Instagram/TikTok/YouTube/etc видео и шлёт владельцу.

Архитектура swarm:
- hub шлёт b2b JSON {id, method:"download", args:{url, owner_id}}
- video-bot скачивает yt-dlp, sendVideo напрямую owner-у
- отвечает hub-у через b2b {id, ok}

ВАЖНО: owner должен один раз /start этому боту, иначе Telegram запретит первое сообщение.
Если так — возвращаем error=owner_not_started, hub передаст подсказку.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from aiogram import Bot, Dispatcher, F  # noqa: E402
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402
from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.types import FSInputFile, Message  # noqa: E402
import yt_dlp  # noqa: E402


VIDEO_BOT_TOKEN = os.environ["VIDEO_BOT_TOKEN"]
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
OUTBOUND_PROXY = (os.environ.get("OUTBOUND_PROXY") or "").strip() or None
HUB_BOT_USERNAME = os.environ.get("HUB_BOT_USERNAME", "oblivionares_bot").lstrip("@")

MAX_RESPONSE_CHARS = 4000
MAX_VIDEO_BYTES = 50_000_000  # Telegram bot API limit для send_video — 50 МБ

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("video-bot")

if OUTBOUND_PROXY:
    os.environ.setdefault("HTTPS_PROXY", OUTBOUND_PROXY)
    os.environ.setdefault("HTTP_PROXY", OUTBOUND_PROXY)
    log.info("OUTBOUND_PROXY active")

_session = AiohttpSession(proxy=OUTBOUND_PROXY) if OUTBOUND_PROXY else AiohttpSession()
bot = Bot(token=VIDEO_BOT_TOKEN, session=_session)
dp = Dispatcher()


def _ytdlp_opts(tmpdir: str) -> dict:
    opts = {
        "outtmpl": f"{tmpdir}/%(id)s.%(ext)s",
        # пробуем mp4 в один файл (без mux), сначала маленькие — экономим время и Telegram limit
        "format": "best[ext=mp4][filesize<50M]/best[ext=mp4]/best[filesize<50M]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_VIDEO_BYTES,
    }
    if OUTBOUND_PROXY:
        opts["proxy"] = OUTBOUND_PROXY
    return opts


async def _download_video(url: str) -> tuple[str, str]:
    """Запускает yt-dlp в thread. Возвращает (filepath, title)."""
    tmpdir = tempfile.mkdtemp(prefix="ytdl_")

    def _sync_download():
        with yt_dlp.YoutubeDL(_ytdlp_opts(tmpdir)) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp может вернуть info-list для playlists, но мы их отключили
            if isinstance(info, dict) and info.get("entries"):
                info = info["entries"][0]
            filepath = ydl.prepare_filename(info)
            title = info.get("title", "video")
            return filepath, title

    return await asyncio.to_thread(_sync_download)


async def handle_download(args: dict) -> dict:
    url = (args.get("url") or "").strip()
    owner_id = args.get("owner_id")
    if not url or not owner_id:
        return {"ok": False, "error": "url_and_owner_id_required"}
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "owner_id_must_be_int"}

    # 1. скачиваем
    try:
        filepath, title = await _download_video(url)
    except Exception as e:
        log.warning("download failed: %s — %s", url, e)
        return {"ok": False, "error": "download_failed", "message": str(e)[:200]}

    # 2. проверяем размер
    try:
        size = os.path.getsize(filepath)
    except Exception:
        size = 0

    if size == 0:
        return {"ok": False, "error": "downloaded_empty"}

    if size > MAX_VIDEO_BYTES:
        try:
            os.remove(filepath)
        except Exception:
            pass
        return {
            "ok": False,
            "error": "video_too_large",
            "size_mb": round(size / 1_000_000, 1),
            "limit_mb": MAX_VIDEO_BYTES // 1_000_000,
        }

    # 3. шлём video владельцу напрямую
    me = await bot.get_me()
    try:
        await bot.send_video(
            chat_id=owner_id,
            video=FSInputFile(filepath, filename=f"{title[:60]}.mp4"),
            caption=f"📹 {title[:200]}\n\n🔗 {url[:200]}",
            supports_streaming=True,
        )
    except TelegramForbiddenError:
        # owner не нажимал /start у этого specialist-бота — не можем инициировать чат
        return {
            "ok": False,
            "error": "owner_not_started",
            "specialist_username": me.username,
            "hint": (
                f"владелец должен один раз /start @{me.username} — это требование Telegram. "
                "после этого специалист сможет присылать видео напрямую."
            ),
        }
    except Exception as e:
        log.exception("send_video failed")
        return {"ok": False, "error": "send_failed", "message": str(e)[:200]}
    finally:
        try:
            os.remove(filepath)
            os.rmdir(os.path.dirname(filepath))
        except Exception:
            pass

    return {
        "ok": True,
        "title": title,
        "size_mb": round(size / 1_000_000, 1),
    }


METHODS = {"download": handle_download}


# ───────────── handlers ─────────────


@dp.message(F.from_user.is_bot, F.text)
async def on_hub_message(message: Message) -> None:
    if not message.from_user:
        return
    if message.from_user.username != HUB_BOT_USERNAME:
        log.warning("rejecting message from unknown bot @%s", message.from_user.username)
        return

    try:
        payload = json.loads(message.text)
    except json.JSONDecodeError:
        log.warning("invalid json from hub")
        return

    req_id = payload.get("id")
    method = payload.get("method")
    args = payload.get("args") or {}

    if not req_id or not method:
        return

    handler = METHODS.get(method)
    if not handler:
        result = {"id": req_id, "ok": False, "error": f"unknown_method:{method}"}
    else:
        try:
            inner = await handler(args)
            result = {"id": req_id, **inner}
        except Exception as e:
            log.exception("method %s failed", method)
            result = {
                "id": req_id,
                "ok": False,
                "error": type(e).__name__,
                "message": str(e)[:200],
            }

    response_text = json.dumps(result, ensure_ascii=False)
    if len(response_text) > MAX_RESPONSE_CHARS:
        response_text = response_text[:MAX_RESPONSE_CHARS]

    try:
        await bot.send_message(chat_id=f"@{HUB_BOT_USERNAME}", text=response_text)
    except Exception:
        log.exception("failed to send response to hub (req_id=%s)", req_id)


@dp.message(F.text.in_({"/start", "/help"}))
async def on_start_or_help(message: Message) -> None:
    """Owner /start'ает video-bot — после этого мы можем слать ему файлы."""
    if not message.from_user:
        return
    await message.answer(
        "👋 я video-specialist для Oblivion Assistant.\n\n"
        "буду присылать сюда видео которые я скачал по ссылкам "
        "Instagram / TikTok / YouTube / VK / т.п.\n\n"
        "тут ничего писать мне не надо — просто оставь чат открытым.\n\n"
        "вернись в @oblivionares_bot и попроси «скачай это: <ссылка>»."
    )


async def main() -> None:
    me = await bot.get_me()
    log.info(
        "video-bot online as @%s (id=%d, can_b2b=%s)",
        me.username, me.id, me.can_connect_to_business,
    )
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
