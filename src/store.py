from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import time
import uuid

from .domain import fingerprint


class StateError(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path=str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL, owner TEXT, lease_until REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS plans (
                    request_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, result TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def acquire(self, request, catalog, created_at=None):
        owner=uuid.uuid4().hex
        key=fingerprint(request,catalog)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM requests WHERE request_id=?",(request["request_id"],)).fetchone()
            if row and row["fingerprint"]!=key: raise StateError("idempotency_conflict")
            if row and row["owner"] and row["lease_until"]>time.time(): raise StateError("request_busy")
            if not row:
                state={"request":deepcopy(request),"catalog":deepcopy(catalog),
                       "created_at":created_at or datetime.now(timezone.utc).isoformat(),
                       "package":None,"steps":{},"events":[],"spent_cents":0,"elapsed_minutes":0,
                       "estimate_package":None,"plan_id":None,"status":"pending","reason":None}
                db.execute("INSERT INTO requests VALUES(?,?,?,NULL,0)",
                           (request["request_id"],key,json.dumps(state,ensure_ascii=False)))
            db.execute("UPDATE requests SET owner=?,lease_until=? WHERE request_id=?",
                       (owner,time.time()+120,request["request_id"]))
        return owner

    def release(self, request_id, owner):
        with self.connect() as db:
            db.execute("UPDATE requests SET owner=NULL,lease_until=0 WHERE request_id=? AND owner=?",
                       (request_id,owner))

    def renew(self, request_id, owner):
        with self.connect() as db:
            cur=db.execute("UPDATE requests SET lease_until=? WHERE request_id=? AND owner=? AND lease_until>?",
                           (time.time()+120,request_id,owner,time.time()))
            if cur.rowcount!=1: raise StateError("lease_lost")

    def get(self, request_id):
        with self.connect() as db:
            row=db.execute("SELECT state FROM requests WHERE request_id=?",(request_id,)).fetchone()
            return json.loads(row["state"]) if row else None

    def mutate(self, request_id, owner, callback):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM requests WHERE request_id=?",(request_id,)).fetchone()
            if not row or row["owner"]!=owner or row["lease_until"]<time.time():
                raise StateError("lease_lost")
            state=json.loads(row["state"])
            result=callback(state,db)
            db.execute("UPDATE requests SET state=?,lease_until=? WHERE request_id=?",
                       (json.dumps(state,ensure_ascii=False,allow_nan=False),time.time()+120,request_id))
            return result

    def saved(self):
        with self.connect() as db:
            return [json.loads(row["result"]) for row in db.execute("SELECT result FROM plans ORDER BY rowid DESC LIMIT 100")]
