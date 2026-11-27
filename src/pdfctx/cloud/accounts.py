"""Users, workspaces, sign-in tokens, sessions, API keys and usage, in one SQLite file.

Secrets (magic-link tokens, session tokens, API keys) are stored only as sha256 hashes: a copy of the
database does not let anyone sign in.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..errors import PdfctxError

MAGIC_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
MAGIC_PER_HOUR = 5
KEY_PREFIX = "pk_live_"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.I)


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    pages: int
    monthly: bool  # False: a lifetime allowance (free)
    price_usd: int


PLANS = {
    "free": Plan("free", "Free", 50, False, 0),
    "pro": Plan("pro", "Pro", 2_000, True, 29),
    "team": Plan("team", "Team", 10_000, True, 99),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free', stripe_customer TEXT, stripe_subscription TEXT,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ws_owner ON workspaces(owner_id);
CREATE INDEX IF NOT EXISTS ws_customer ON workspaces(stripe_customer);
CREATE TABLE IF NOT EXISTS magic (hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  hash TEXT UNIQUE NOT NULL,
  hint TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS usage (workspace_id TEXT NOT NULL, month TEXT NOT NULL, pages INTEGER NOT NULL,
  PRIMARY KEY (workspace_id, month));
CREATE TABLE IF NOT EXISTS stripe_events (id TEXT PRIMARY KEY, received_at TEXT NOT NULL);
"""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


@dataclass(frozen=True)
class User:
    id: str
    email: str


@dataclass(frozen=True)
class Workspace:
    id: str
    owner_id: str
    name: str
    plan: str
    stripe_customer: str | None
    stripe_subscription: str | None


class Accounts:
    def __init__(self, path: Path | str, now=_now):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now  # injectable clock for tests
        self._lock = threading.RLock()
        self._local = threading.local()
        self._conns: list[sqlite3.Connection] = []
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            with self._lock:
                self._conns.append(conn)
        return conn

    def close(self) -> None:
        with self._lock:
            for c in self._conns:
                c.close()
            self._conns.clear()
        self._local = threading.local()

    # -- sign-in ---------------------------------------------------------------------------------

    def request_magic(self, email: str) -> str:
        """A single-use sign-in token for `email` (the raw token goes into the emailed link)."""
        email = email.strip().lower()
        if not _EMAIL.match(email):
            raise PdfctxError("enter a valid email address")
        with self._lock:
            hour_ago = _iso(self.now() - timedelta(hours=1))
            (recent,) = self.db.execute(
                "SELECT count(*) FROM magic WHERE email=? AND created_at>?", (email, hour_ago)
            ).fetchone()
            if recent >= MAGIC_PER_HOUR:
                raise PdfctxError("too many sign-in emails; try again in an hour")
            token = secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO magic VALUES (?,?,?,0,?)",
                (_hash(token), email, _iso(self.now() + MAGIC_TTL), _iso(self.now())),
            )
        return token

    def verify_magic(self, token: str) -> User:
        """Use a sign-in token once; creates the user and their workspace on first sign-in."""
        with self._lock:
            row = self.db.execute("SELECT * FROM magic WHERE hash=?", (_hash(token),)).fetchone()
            if row is None or row["used"] or row["expires_at"] < _iso(self.now()):
                raise PdfctxError("this sign-in link is invalid or has expired; request a new one")
            self.db.execute("UPDATE magic SET used=1 WHERE hash=?", (row["hash"],))
            return self._user_for_email(row["email"])

    def _user_for_email(self, email: str) -> User:
        row = self.db.execute("SELECT id, email FROM users WHERE email=?", (email,)).fetchone()
        if row:
            return User(row["id"], row["email"])
        uid, wid = "u_" + secrets.token_hex(8), "w_" + secrets.token_hex(8)
        self.db.execute("BEGIN")
        try:
            self.db.execute("INSERT INTO users VALUES (?,?,?)", (uid, email, _iso(self.now())))
            self.db.execute(
                "INSERT INTO workspaces (id, owner_id, name, created_at) VALUES (?,?,?,?)",
                (wid, uid, email.split("@")[0], _iso(self.now())),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return User(uid, email)

    def create_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?)", (_hash(token), user.id, _iso(self.now() + SESSION_TTL))
            )
        return token

    def user_for_session(self, token: str | None) -> User | None:
        if not token:
            return None
        row = self.db.execute(
            "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.hash=? AND s.expires_at>?",
            (_hash(token), _iso(self.now())),
        ).fetchone()
        return User(row["id"], row["email"]) if row else None

    def end_session(self, token: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM sessions WHERE hash=?", (_hash(token),))

    # -- workspaces ------------------------------------------------------------------------------

    @staticmethod
    def _ws(row) -> Workspace:
        return Workspace(
            row["id"],
            row["owner_id"],
            row["name"],
            row["plan"],
            row["stripe_customer"],
            row["stripe_subscription"],
        )

    def workspace_for_user(self, user: User) -> Workspace:
        row = self.db.execute(
            "SELECT * FROM workspaces WHERE owner_id=? ORDER BY created_at LIMIT 1", (user.id,)
        ).fetchone()
        if row is None:
            raise PdfctxError("no workspace for this user")
        return self._ws(row)

    def workspace(self, workspace_id: str) -> Workspace | None:
        row = self.db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        return self._ws(row) if row else None

    def workspace_by_customer(self, customer: str) -> Workspace | None:
        row = self.db.execute("SELECT * FROM workspaces WHERE stripe_customer=?", (customer,)).fetchone()
        return self._ws(row) if row else None

    def set_plan(
        self, workspace_id: str, plan: str, customer: str | None = None, subscription: str | None = None
    ) -> None:
        if plan not in PLANS:
            raise PdfctxError(f"unknown plan '{plan}'")
        with self._lock:
            self.db.execute(
                "UPDATE workspaces SET plan=?, stripe_customer=coalesce(?, stripe_customer), "
                "stripe_subscription=? WHERE id=?",
                (plan, customer, subscription, workspace_id),
            )

    # -- API keys --------------------------------------------------------------------------------

    def create_key(self, workspace_id: str, name: str) -> tuple[str, dict]:
        """Returns the raw key (shown once) and its public record."""
        name = (name or "key").strip()[:60]
        raw = KEY_PREFIX + secrets.token_urlsafe(24)
        kid = "k_" + secrets.token_hex(6)
        with self._lock:
            self.db.execute(
                "INSERT INTO api_keys VALUES (?,?,?,?,?,?,NULL)",
                (kid, workspace_id, _hash(raw), raw[-4:], name, _iso(self.now())),
            )
        return raw, {"id": kid, "name": name, "hint": "…" + raw[-4:], "created_at": _iso(self.now())}

    def list_keys(self, workspace_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, name, hint, created_at FROM api_keys WHERE workspace_id=? AND revoked_at IS NULL "
            "ORDER BY created_at",
            (workspace_id,),
        )
        return [
            {"id": r["id"], "name": r["name"], "hint": "…" + r["hint"], "created_at": r["created_at"]}
            for r in rows
        ]

    def revoke_key(self, workspace_id: str, key_id: str) -> bool:
        with self._lock:
            cur = self.db.execute(
                "UPDATE api_keys SET revoked_at=? WHERE id=? AND workspace_id=? AND revoked_at IS NULL",
                (_iso(self.now()), key_id, workspace_id),
            )
        return cur.rowcount == 1

    def workspace_for_key(self, raw: str | None) -> Workspace | None:
        if not raw or not raw.startswith(KEY_PREFIX):
            return None
        row = self.db.execute(
            "SELECT w.* FROM api_keys k JOIN workspaces w ON w.id=k.workspace_id "
            "WHERE k.hash=? AND k.revoked_at IS NULL",
            (_hash(raw),),
        ).fetchone()
        return self._ws(row) if row else None

    # -- usage and limits ------------------------------------------------------------------------

    def _month(self) -> str:
        return self.now().strftime("%Y-%m")

    def pages_used(self, ws: Workspace) -> int:
        plan = PLANS[ws.plan]
        if plan.monthly:
            row = self.db.execute(
                "SELECT pages FROM usage WHERE workspace_id=? AND month=?", (ws.id, self._month())
            ).fetchone()
            return row["pages"] if row else 0
        (total,) = self.db.execute(
            "SELECT coalesce(sum(pages), 0) FROM usage WHERE workspace_id=?", (ws.id,)
        ).fetchone()
        return total

    def check_quota(self, ws: Workspace, pages: int) -> None:
        plan = PLANS[ws.plan]
        used = self.pages_used(ws)
        if used + pages > plan.pages:
            period = "this month" if plan.monthly else "on the free plan"
            raise QuotaExceeded(
                f"this upload has {pages} pages; {used} of {plan.pages} pages are already used {period}. "
                "Upgrade the plan to add more."
            )

    def add_usage(self, ws: Workspace, pages: int) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO usage VALUES (?,?,?) "
                "ON CONFLICT(workspace_id, month) DO UPDATE SET pages=pages+?",
                (ws.id, self._month(), pages, pages),
            )

    # -- billing events --------------------------------------------------------------------------

    def first_time_event(self, event_id: str) -> bool:
        """True once per Stripe event id (Stripe retries deliveries)."""
        with self._lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO stripe_events VALUES (?,?)", (event_id, _iso(self.now()))
            )
        return cur.rowcount == 1


class QuotaExceeded(PdfctxError):
    """The workspace's plan does not allow more pages."""
