"""Быстрые regex-парсеры, которые выполняются ДО основного LLM-pass.

Цель — не плодить лишние tool-calls для простых «да/нет» / «вкл/выкл» / статусов.
LLM иногда упорно не зовёт set_status даже с явным промптом — regex надёжнее.
"""

import re


def parse_memory_toggle(text: str) -> bool | None:
    normalized = " ".join(text.casefold().strip().split())
    enable = {
        "включи память",
        "включить память",
        "память включи",
        "память включить",
        "memory on",
        "enable memory",
    }
    disable = {
        "выключи память",
        "выключить память",
        "память выключи",
        "память выключить",
        "memory off",
        "disable memory",
    }
    if normalized in enable:
        return True
    if normalized in disable:
        return False
    return None


def parse_outbound_confirmation(text: str) -> bool | None:
    normalized = " ".join(text.casefold().strip().split())
    yes = {"да", "отправь", "отправляй", "ок", "окей", "yes", "send", "go"}
    no = {"нет", "отмена", "не отправляй", "cancel", "no"}
    if normalized in yes:
        return True
    if normalized in no:
        return False
    return None


# ---------- статус (set_status / clear_status) ----------

# во всех regex ниже используем 'е' (а не 'ё') — вход нормализуется в parse_status_command
# через _normalize_yo. это покрывает частую опечатку «пошел/лег/ушел» без ё.

# «[если что/если кто спросит,] говори/скажи/передавай [моим] <scope> что я <STATUS>»
_STATUS_SCOPED_RE = re.compile(
    r"^(?:если\s+(?:что|кто\s+спросит)[,.\s]+)?"
    r"(?:говори|скажи|передавай|пиши|отвечай)\s+"
    r"(?:моим\s+)?(работе|коллегам|боссу|начальству|друзьям|семье|девушке|жене|мужу|маме|папе)"
    r"[,.\s]+что\s+я\s+(.+)$",
    re.IGNORECASE,
)

# «[если что/если кто спросит,] [говори/скажи/передавай] [всем] что я <STATUS>»
# принимает обе перестановки: «говори всем», «всем говори», просто «говори»
_STATUS_ALL_RE = re.compile(
    r"^(?:если\s+(?:что|кто\s+спросит)[,.\s]+)?"
    r"(?:"
    r"(?:говори|скажи|передавай|пиши|отвечай)(?:\s+всем)?"
    r"|"
    r"всем\s+(?:говори|скажи|передавай|пиши|отвечай)"
    r")"
    r"[,.\s]+что\s+я\s+(.+)$",
    re.IGNORECASE,
)

# «[я] в отпуске», «[я] сплю», «[я] пошел/ушел/лег ...» — «я» опционально
_STATUS_DECL_RE = re.compile(
    r"^(?:я\s+)?("
    r"в\s+отпуске(?:\s.+)?|"
    r"в\s+командировке(?:\s.+)?|"
    r"в\s+дороге(?:\s.+)?|"
    r"в\s+пути(?:\s.+)?|"
    r"на\s+встрече(?:\s.+)?|"
    r"на\s+созвоне(?:\s.+)?|"
    r"на\s+вебинаре(?:\s.+)?|"
    r"на\s+обеде(?:\s.+)?|"
    r"сплю(?:\s.+)?|"
    r"лег\s+спать(?:\s.+)?|"
    r"иду\s+спать(?:\s.+)?|"
    r"пойду\s+спать(?:\s.+)?|"
    r"лягу\s+спать(?:\s.+)?|"
    r"ложусь\s+спать(?:\s.+)?|"
    r"спать(?:\s.+)?|"
    r"пошел\s+\S+.*|"
    r"ушел\s+\S+.*|"
    r"вышел\s+\S+.*|"
    r"уехал\s+\S+.*|"
    r"уехала\s+\S+.*|"
    r"улетел\s+\S+.*|"
    r"занят(?:\s.+)?|"
    r"занята(?:\s.+)?"
    r")$",
    re.IGNORECASE,
)

# duration внутри статуса
# нормальный порядок: «на 3 часа», «на 2 дня», «на неделю»
_DURATION_RE = re.compile(
    r"\bна\s+(\d+)?\s*(час[аов]*|мин[ут]*|ден[ьь]|дн[яейьiеи]+|недел[юияей]+)",
    re.IGNORECASE,
)
# обратный порядок: «минут на 40», «час на 2», «дней на 5»
_DURATION_RE_INVERTED = re.compile(
    r"\b(час[аов]*|мин[ут]*|ден[ьь]|дн[яейьiеи]+|недел[юияей]+)\s+на\s+(\d+)",
    re.IGNORECASE,
)

# clear-команды
_STATUS_CLEAR_RE = re.compile(
    r"^("
    r"вернулся|вернулась|"
    r"сними\s+статус|убери\s+статус|"
    r"отмени\s+(?:отпуск|статус)|"
    r"я\s+(?:снова|опять|уже)\s+(?:тут|в\s+строю|свободен|свободна)"
    r")[.!?]*$",
    re.IGNORECASE,
)


_SCOPE_MAP = {
    "работе": ["work"],
    "коллегам": ["work"],
    "боссу": ["work"],
    "начальству": ["work"],
    "друзьям": ["friend"],
    "семье": ["family"],
    "девушке": ["girlfriend"],
    "жене": ["family", "wife"],
    "мужу": ["family", "husband"],
    "маме": ["family"],
    "папе": ["family"],
}


def _extract_duration(status_text: str) -> tuple[int | None, int | None]:
    """Из строки статуса вытащить hours/days. Поддерживает оба порядка:
    «на 3 часа» и «часа на 3» / «минут на 40»."""
    # пробуем нормальный порядок
    m = _DURATION_RE.search(status_text)
    if m:
        n_str = m.group(1)
        unit = (m.group(2) or "").lower()
    else:
        # пробуем обратный «<unit> на N»
        m = _DURATION_RE_INVERTED.search(status_text)
        if not m:
            return None, None
        unit = (m.group(1) or "").lower()
        n_str = m.group(2)

    n = int(n_str) if n_str else 1
    if unit.startswith("час"):
        return n, None
    if unit.startswith("мин"):
        # минуты округляем вверх до часа (минимум 1ч)
        return max(1, (n + 59) // 60), None
    if unit.startswith("ден") or unit.startswith("дн"):
        return None, n
    if unit.startswith("недел"):
        return None, n * 7
    return None, None


def _normalize_yo(text: str) -> str:
    """Привести ё → е, Ё → Е. Русские часто пишут «пошел/лег» без ё."""
    return text.replace("ё", "е").replace("Ё", "Е")


def parse_status_command(text: str) -> dict | None:
    """Если текст похож на установку статуса — вернуть {text, hours?, days?, scopes?}.

    Иначе None — пусть едет в LLM-pass как обычный диалог.
    """
    s = " ".join(text.strip().split()).rstrip(".!?")
    s = _normalize_yo(s)

    status_text: str | None = None
    scopes: list[str] | None = None

    m = _STATUS_SCOPED_RE.match(s)
    if m:
        scope_word = m.group(1).lower()
        scopes = _SCOPE_MAP.get(scope_word) or [scope_word]
        status_text = m.group(2).strip()
    else:
        m = _STATUS_ALL_RE.match(s)
        if m:
            status_text = m.group(1).strip()
        else:
            m = _STATUS_DECL_RE.match(s)
            if m:
                status_text = m.group(1).strip()

    if not status_text:
        return None

    hours, days = _extract_duration(status_text)

    result: dict = {"text": status_text}
    if hours is not None:
        result["hours"] = hours
    if days is not None:
        result["days"] = days
    if scopes:
        result["scopes"] = scopes
    return result


def parse_status_clear(text: str) -> bool:
    s = " ".join(text.strip().split()).rstrip(".!?")
    s = _normalize_yo(s)
    return bool(_STATUS_CLEAR_RE.match(s))
