import json
import sqlite3
import threading
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "memory_consent": False,
    "disclaimer": False,
    "stop_topics": [],
    "reply_scope": "all",  # all | known | none
    "paused": False,
}


class SqliteDatabase:
    def __init__(self, file):
        self._conn = sqlite3.connect(file, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._cursor = self._conn.cursor()
        self._lock = threading.Lock()

    @staticmethod
    def _parse_row(row: sqlite3.Row):
        t = row["type"]
        if t == "bool":
            return row["val"] == "1"
        if t == "int":
            return int(row["val"])
        if t == "str":
            return row["val"]
        return json.loads(row["val"])

    def _execute(self, module: str, *args, **kwargs) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self._cursor.execute(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if str(e).startswith("no such table"):
                    self._cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS '{module}' (
                            var TEXT UNIQUE NOT NULL,
                            val TEXT NOT NULL,
                            type TEXT NOT NULL
                        )
                        """
                    )
                    self._conn.commit()
                    return self._cursor.execute(*args, **kwargs)
                raise

    def get(self, module: str, variable: str, default=None):
        cur = self._execute(
            module,
            f"SELECT * FROM '{module}' WHERE var=:var",
            {"var": variable},
        )
        row = cur.fetchone()
        return self._parse_row(row) if row else default

    def set(self, module: str, variable: str, value) -> bool:
        if isinstance(value, bool):
            val, typ = ("1" if value else "0"), "bool"
        elif isinstance(value, int):
            val, typ = str(value), "int"
        elif isinstance(value, str):
            val, typ = value, "str"
        else:
            val, typ = json.dumps(value), "json"

        self._execute(
            module,
            f"""
            INSERT INTO '{module}' VALUES (:var, :val, :type)
            ON CONFLICT (var) DO
            UPDATE SET val=:val, type=:type WHERE var=:var
            """,
            {"var": variable, "val": val, "type": typ},
        )
        self._conn.commit()
        return True

    def remove(self, module: str, variable: str):
        self._execute(
            module,
            f"DELETE FROM '{module}' WHERE var=:var",
            {"var": variable},
        )
        self._conn.commit()

    def get_collection(self, module: str) -> dict:
        cur = self._execute(module, f"SELECT * FROM '{module}'")
        return {row["var"]: self._parse_row(row) for row in cur}

    def close(self):
        self._conn.commit()
        self._conn.close()

    # ---------- Chat history (per-contact dialog log) ----------

    def chat_history_key(self, user_id: int) -> str:
        return f"core.oblivion.user_{user_id}"

    def get_chat_history(self, user_id: int) -> list:
        return self.get(self.chat_history_key(user_id), "chat_history", default=[])

    def set_chat_history(self, user_id: int, history: list) -> None:
        self.set(self.chat_history_key(user_id), "chat_history", history)

    def wipe_chat_history(self, user_id: int) -> None:
        self.remove(self.chat_history_key(user_id), "chat_history")

    # ---------- Owner-bot DM history (диалог владельца с ботом-ассистентом) ----------

    def owner_chat_key(self, owner_id: int) -> str:
        return f"oblivion.owner_chat.{owner_id}"

    def get_owner_chat(self, owner_id: int) -> list:
        return self.get(self.owner_chat_key(owner_id), "history", default=[])

    def set_owner_chat(self, owner_id: int, history: list) -> None:
        self.set(self.owner_chat_key(owner_id), "history", history)

    def wipe_owner_chat(self, owner_id: int) -> None:
        self.remove(self.owner_chat_key(owner_id), "history")

    # ---------- Owners (Business connection owners) ----------
    # запись = всё, что бот знает про владельца на уровне инфраструктуры:
    # связь с Business, текущая фаза онбординга, признак paused и т.д.

    OWNERS = "oblivion.owners"

    def save_owner(self, owner_id: int, **fields) -> None:
        existing = self.get_owner(owner_id) or {}
        existing.update(fields)
        self.set(self.OWNERS, str(owner_id), existing)

    def get_owner(self, owner_id: int) -> dict | None:
        return self.get(self.OWNERS, str(owner_id))

    def list_owners(self) -> dict[str, dict]:
        return self.get_collection(self.OWNERS)

    def remove_owner(self, owner_id: int) -> None:
        self.remove(self.OWNERS, str(owner_id))

    def set_owner_state(self, owner_id: int, state: str) -> None:
        self.save_owner(owner_id, state=state)

    def find_owner_by_business_connection(self, bc_id: str) -> tuple[int, dict] | None:
        for k, v in self.list_owners().items():
            if v.get("business_connection_id") == bc_id:
                return int(k), v
        return None

    # ---------- Identity narrative (layer 1) ----------

    IDENTITY = "oblivion.identity"

    def save_identity(self, owner_id: int, narrative: str) -> None:
        self.set(self.IDENTITY, str(owner_id), narrative)

    def get_identity(self, owner_id: int) -> str | None:
        return self.get(self.IDENTITY, str(owner_id))

    def wipe_identity(self, owner_id: int) -> None:
        self.remove(self.IDENTITY, str(owner_id))

    # ---------- Settings ----------

    SETTINGS = "oblivion.settings"

    def get_settings(self, owner_id: int) -> dict:
        stored = self.get(self.SETTINGS, str(owner_id)) or {}
        return {**DEFAULT_SETTINGS, **stored}

    def get_setting(self, owner_id: int, key: str, default=None):
        return self.get_settings(owner_id).get(key, default)

    def save_settings(self, owner_id: int, **fields) -> None:
        current = self.get_settings(owner_id)
        current.update(fields)
        # сохраняем только то, что отличается от дефолта — экономим место
        diff = {k: v for k, v in current.items() if DEFAULT_SETTINGS.get(k) != v}
        if diff:
            self.set(self.SETTINGS, str(owner_id), diff)
        else:
            self.remove(self.SETTINGS, str(owner_id))

    # ---------- Contacts (layer 2: relationship per-contact) ----------
    # один module на каждого owner, чтобы не плодить общий стол и не
    # путать контактов разных пользователей.

    def _contacts_module(self, owner_id: int) -> str:
        return f"oblivion.contacts.{owner_id}"

    def save_contact(self, owner_id: int, contact_id: int, **fields) -> None:
        module = self._contacts_module(owner_id)
        existing = self.get(module, str(contact_id)) or {}
        existing.update(fields)
        self.set(module, str(contact_id), existing)

    def get_contact(self, owner_id: int, contact_id: int) -> dict | None:
        return self.get(self._contacts_module(owner_id), str(contact_id))

    def list_contacts(self, owner_id: int) -> dict[str, dict]:
        return self.get_collection(self._contacts_module(owner_id))

    def forget_contact(self, owner_id: int, contact_id: int) -> None:
        self.remove(self._contacts_module(owner_id), str(contact_id))


db = SqliteDatabase("db.sqlite3")
