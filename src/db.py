import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "memory_consent": False,
    "disclaimer": False,
    "stop_topics": [],
    "reply_scope": "all",  # all | known | none
    "paused": False,
    "proactive_enabled": False,
    "music_enabled": True,
    "gifs_enabled": True,
    "daily_checkin_enabled": True,
    "quiet_hours": {"from": "23:00", "to": "09:00"},
    "proactive_daily_budget": 2,
    "external_network_consent": False,  # разрешение на скиллы которые ходят в интернет (через swarm)
}


class SqliteDatabase:
    def __init__(self, file):
        self._conn = sqlite3.connect(file, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._cursor = self._conn.cursor()
        self._lock = threading.Lock()
        self._init_structured_tables()

    def _init_structured_tables(self) -> None:
        with self._lock:
            self._cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_facts_owner_subject
                ON facts (owner_id, subject)
                """
            )
            self._cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    skill TEXT NOT NULL,
                    args TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_log_owner_created
                ON audit_log (owner_id, created_at)
                """
            )
            self._cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    due_at TEXT,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reminded_at TEXT,
                    completed_at TEXT
                )
                """
            )
            self._cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_owner_status_due
                ON tasks (owner_id, status, due_at)
                """
            )
            self._cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS proactive_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_proactive_log_owner_created
                ON proactive_log (owner_id, created_at)
                """
            )
            self._cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS recurring_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    query TEXT NOT NULL,
                    hour_local INTEGER NOT NULL,
                    minute_local INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recurring_jobs_owner_enabled
                ON recurring_jobs (owner_id, enabled)
                """
            )
            self._conn.commit()

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

    def find_contact(self, owner_id: int, target: str) -> tuple[int, dict] | None:
        needle = target.strip().casefold().lstrip("@").replace("ё", "е")
        if not needle:
            return None

        for contact_id, contact in self.list_contacts(owner_id).items():
            haystack = " ".join(
                str(contact.get(key) or "")
                for key in ("username", "first_name", "last_name", "full_name")
            ).casefold().lstrip("@").replace("ё", "е")
            if needle in haystack:
                return int(contact_id), contact
        return None

    # ---------- Facts memory ----------

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _memory_search_terms(text: str) -> list[str]:
        terms = []
        for raw in text.casefold().replace("ё", "е").split():
            term = raw.strip(".,!?;:()[]{}\"'«»")
            if len(term) < 2:
                continue
            terms.append(term)
            stem = term.rstrip("аеуыоиемюяь")
            if len(stem) >= 3 and stem != term:
                terms.append(stem)
        return terms

    def find_existing_fact(
        self,
        owner_id: int,
        subject: str,
        fact: str,
    ) -> dict | None:
        """Найти точно такой же факт (subject + fact, case-insensitive). Для dedup."""
        subject_norm = subject.strip().casefold()
        fact_norm = fact.strip().casefold()
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, owner_id, subject, fact, source, created_at
                FROM facts
                WHERE owner_id = :owner_id
                  AND lower(subject) = :subject
                  AND lower(fact) = :fact
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {
                    "owner_id": owner_id,
                    "subject": subject_norm,
                    "fact": fact_norm,
                },
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def add_fact(self, owner_id: int, subject: str, fact: str, source: str) -> dict:
        created_at = self.now_iso()
        with self._lock:
            cur = self._cursor.execute(
                """
                INSERT INTO facts (owner_id, subject, fact, source, created_at)
                VALUES (:owner_id, :subject, :fact, :source, :created_at)
                """,
                {
                    "owner_id": owner_id,
                    "subject": subject.strip(),
                    "fact": fact.strip(),
                    "source": source,
                    "created_at": created_at,
                },
            )
            self._conn.commit()
            fact_id = cur.lastrowid
        return {
            "id": fact_id,
            "owner_id": owner_id,
            "subject": subject.strip(),
            "fact": fact.strip(),
            "source": source,
            "created_at": created_at,
        }

    def recall_facts(self, owner_id: int, query: str, limit: int = 8) -> list[dict]:
        needle = query.strip().casefold().replace("ё", "е")
        terms = self._memory_search_terms(query)
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, owner_id, subject, fact, source, created_at
                FROM facts
                WHERE owner_id = :owner_id
                ORDER BY created_at DESC
                """,
                {"owner_id": owner_id},
            )
            rows = [dict(row) for row in cur.fetchall()]

        if not needle:
            return rows[:limit]

        matches = []
        for row in rows:
            haystack = f"{row['subject']} {row['fact']}".casefold().replace("ё", "е")
            if needle in haystack or any(term in haystack for term in terms[:5]):
                matches.append(row)
            if len(matches) >= limit:
                break
        return matches

    def forget_facts(self, owner_id: int, target: str) -> int:
        needle = target.strip().casefold().replace("ё", "е")
        terms = self._memory_search_terms(target)
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, subject, fact
                FROM facts
                WHERE owner_id = :owner_id
                """,
                {"owner_id": owner_id},
            )
            ids = [
                row["id"]
                for row in cur.fetchall()
                if (
                    needle
                    in (
                        haystack := f"{row['subject']} {row['fact']}"
                        .casefold()
                        .replace("ё", "е")
                    )
                    or any(term in haystack for term in terms[:5])
                )
            ]
            if not ids:
                return 0

            placeholders = ",".join("?" for _ in ids)
            cur = self._cursor.execute(
                f"DELETE FROM facts WHERE owner_id = ? AND id IN ({placeholders})",
                [owner_id, *ids],
            )
            deleted = cur.rowcount
            self._conn.commit()
            if deleted:
                self._cursor.execute("VACUUM")
        return deleted

    # ---------- Audit log ----------

    def append_audit_log(
        self,
        owner_id: int,
        skill: str,
        args: dict,
        result: dict | str,
    ) -> None:
        with self._lock:
            self._cursor.execute(
                """
                INSERT INTO audit_log (owner_id, skill, args, result, created_at)
                VALUES (:owner_id, :skill, :args, :result, :created_at)
                """,
                {
                    "owner_id": owner_id,
                    "skill": skill,
                    "args": json.dumps(args, ensure_ascii=False),
                    "result": json.dumps(result, ensure_ascii=False)
                    if not isinstance(result, str)
                    else result,
                    "created_at": self.now_iso(),
                },
            )
            self._conn.commit()

    # ---------- Tasks ----------

    def add_task(
        self,
        owner_id: int,
        title: str,
        due_at: str | None,
        source: str,
    ) -> dict:
        created_at = self.now_iso()
        with self._lock:
            cur = self._cursor.execute(
                """
                INSERT INTO tasks (owner_id, title, due_at, status, source, created_at)
                VALUES (:owner_id, :title, :due_at, 'open', :source, :created_at)
                """,
                {
                    "owner_id": owner_id,
                    "title": title.strip(),
                    "due_at": due_at,
                    "source": source,
                    "created_at": created_at,
                },
            )
            self._conn.commit()
            task_id = cur.lastrowid
        return {
            "id": task_id,
            "owner_id": owner_id,
            "title": title.strip(),
            "due_at": due_at,
            "status": "open",
            "source": source,
            "created_at": created_at,
            "reminded_at": None,
            "completed_at": None,
        }

    def list_tasks(
        self,
        owner_id: int,
        status: str | None = "open",
        limit: int = 20,
    ) -> list[dict]:
        query = """
            SELECT id, owner_id, title, due_at, status, source, created_at, reminded_at, completed_at
            FROM tasks
            WHERE owner_id = :owner_id
        """
        params: dict[str, Any] = {"owner_id": owner_id, "limit": limit}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY due_at IS NULL, due_at ASC, created_at DESC LIMIT :limit"
        with self._lock:
            cur = self._cursor.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def due_tasks(self, now_iso: str, limit: int = 20) -> list[dict]:
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, owner_id, title, due_at, status, source, created_at, reminded_at, completed_at
                FROM tasks
                WHERE status = 'open'
                  AND due_at IS NOT NULL
                  AND due_at <= :now_iso
                  AND reminded_at IS NULL
                ORDER BY due_at ASC
                LIMIT :limit
                """,
                {"now_iso": now_iso, "limit": limit},
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_task_reminded(self, task_id: int) -> None:
        with self._lock:
            self._cursor.execute(
                "UPDATE tasks SET reminded_at = :reminded_at WHERE id = :task_id",
                {"task_id": task_id, "reminded_at": self.now_iso()},
            )
            self._conn.commit()

    def complete_task(self, owner_id: int, task_id: int) -> dict | None:
        completed_at = self.now_iso()
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, owner_id, title, due_at, status, source, created_at, reminded_at, completed_at
                FROM tasks
                WHERE owner_id = :owner_id AND id = :task_id
                """,
                {"owner_id": owner_id, "task_id": task_id},
            )
            row = cur.fetchone()
            if not row:
                return None
            self._cursor.execute(
                """
                UPDATE tasks
                SET status = 'done', completed_at = :completed_at
                WHERE owner_id = :owner_id AND id = :task_id
                """,
                {
                    "owner_id": owner_id,
                    "task_id": task_id,
                    "completed_at": completed_at,
                },
            )
            self._conn.commit()
            task = dict(row)
            task["status"] = "done"
            task["completed_at"] = completed_at
            return task

    # ---------- Proactive log ----------

    def add_proactive_log(self, owner_id: int, kind: str, text: str) -> None:
        with self._lock:
            self._cursor.execute(
                """
                INSERT INTO proactive_log (owner_id, kind, text, created_at)
                VALUES (:owner_id, :kind, :text, :created_at)
                """,
                {
                    "owner_id": owner_id,
                    "kind": kind,
                    "text": text,
                    "created_at": self.now_iso(),
                },
            )
            self._conn.commit()

    def proactive_count_since(self, owner_id: int, since_iso: str) -> int:
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT COUNT(*) AS n
                FROM proactive_log
                WHERE owner_id = :owner_id AND created_at >= :since_iso
                """,
                {"owner_id": owner_id, "since_iso": since_iso},
            )
            return int(cur.fetchone()["n"])

    # ---------- Recurring jobs (daily digests etc.) ----------

    def add_recurring_job(
        self,
        owner_id: int,
        kind: str,
        query: str,
        hour_local: int,
        minute_local: int = 0,
    ) -> dict:
        created_at = self.now_iso()
        with self._lock:
            cur = self._cursor.execute(
                """
                INSERT INTO recurring_jobs
                    (owner_id, kind, query, hour_local, minute_local, enabled, created_at)
                VALUES (:owner_id, :kind, :query, :hour, :minute, 1, :created_at)
                """,
                {
                    "owner_id": owner_id,
                    "kind": kind,
                    "query": query.strip(),
                    "hour": hour_local,
                    "minute": minute_local,
                    "created_at": created_at,
                },
            )
            self._conn.commit()
            job_id = cur.lastrowid
        return {
            "id": job_id,
            "owner_id": owner_id,
            "kind": kind,
            "query": query.strip(),
            "hour_local": hour_local,
            "minute_local": minute_local,
            "enabled": 1,
            "last_run_at": None,
            "created_at": created_at,
        }

    def list_recurring_jobs(self, owner_id: int, only_enabled: bool = True) -> list[dict]:
        query = """
            SELECT id, owner_id, kind, query, hour_local, minute_local,
                   enabled, last_run_at, created_at
            FROM recurring_jobs
            WHERE owner_id = :owner_id
        """
        params: dict[str, Any] = {"owner_id": owner_id}
        if only_enabled:
            query += " AND enabled = 1"
        query += " ORDER BY hour_local, minute_local, id"
        with self._lock:
            cur = self._cursor.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def list_all_recurring_jobs(self) -> list[dict]:
        """Все активные jobs — для шедулера, по всем владельцам."""
        with self._lock:
            cur = self._cursor.execute(
                """
                SELECT id, owner_id, kind, query, hour_local, minute_local,
                       enabled, last_run_at, created_at
                FROM recurring_jobs
                WHERE enabled = 1
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def disable_recurring_job(self, owner_id: int, job_id: int) -> bool:
        with self._lock:
            cur = self._cursor.execute(
                """
                UPDATE recurring_jobs SET enabled = 0
                WHERE owner_id = :owner_id AND id = :job_id AND enabled = 1
                """,
                {"owner_id": owner_id, "job_id": job_id},
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_recurring_job_run(self, job_id: int) -> None:
        with self._lock:
            self._cursor.execute(
                "UPDATE recurring_jobs SET last_run_at = :ts WHERE id = :id",
                {"id": job_id, "ts": self.now_iso()},
            )
            self._conn.commit()

    def last_proactive(self, owner_id: int, kind: str | None = None) -> dict | None:
        query = """
            SELECT id, owner_id, kind, text, created_at
            FROM proactive_log
            WHERE owner_id = :owner_id
        """
        params: dict[str, Any] = {"owner_id": owner_id}
        if kind:
            query += " AND kind = :kind"
            params["kind"] = kind
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._lock:
            cur = self._cursor.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None


import os as _os

# SQLITE_PATH позволяет указать абсолютный путь (для docker volume).
# по умолчанию — рядом с db.py (для локальной разработки).
_sqlite_path = _os.environ.get("SQLITE_PATH")
if _sqlite_path:
    db = SqliteDatabase(_sqlite_path)
else:
    db = SqliteDatabase(Path(__file__).resolve().parent / "db.sqlite3")
