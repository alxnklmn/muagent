"""Загрузка и подбор треков из curated JSON. Временная заглушка.

Будет заменена на реальный музыкальный API в одной из следующих фаз.
"""

import json
import random
from pathlib import Path


TRACKS_PATH = Path(__file__).resolve().parent.parent / "assets" / "tracks.json"
TRACKS: list[dict] = json.loads(TRACKS_PATH.read_text(encoding="utf-8"))


def pick_track(mood: str | None = None) -> dict:
    candidates = [item for item in TRACKS if not mood or item.get("mood") == mood]
    if not candidates:
        candidates = TRACKS
    return random.choice(candidates)


def format_track(track: dict) -> str:
    return f"{track['title']}\n{track['url']}\n\n{track['note']}"
