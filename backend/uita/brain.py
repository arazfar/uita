"""Shared team memory: every agent reads active entries before work and writes after.

A write that disagrees with an active entry on the same topic does not overwrite it.
Both entries become disputed until the arbiter resolves them; readers never see a
disputed claim as fact. Superseded entries are retained for lineage.
"""
import json
import sqlite3
import time
import uuid
from pydantic import BaseModel, Field


class Source(BaseModel):
    url: str
    title: str = ''
    quote: str


class Entry(BaseModel):
    id: str
    topic: str
    claim: str
    value: str
    written_by: str
    status: str
    sources: list[Source] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    created: float
    checked_at: float | None = None


class Conflict(BaseModel):
    topic: str
    entries: list[Entry]


def _norm(value):return ' '.join(str(value).lower().split())


class Brain:
    def __init__(self,path=':memory:'):
        self.db=sqlite3.connect(path,timeout=5)
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS brain_entries (id TEXT PRIMARY KEY, topic TEXT NOT NULL, claim TEXT NOT NULL, value TEXT NOT NULL, written_by TEXT NOT NULL, status TEXT NOT NULL, sources TEXT NOT NULL, supersedes TEXT NOT NULL, created REAL NOT NULL, checked_at REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS brain_arbitrations (id TEXT PRIMARY KEY, topic TEXT NOT NULL, verdict TEXT NOT NULL, record TEXT NOT NULL, created REAL NOT NULL)')
        self.db.commit()

    def _entry(self,row):
        return Entry(**{**dict(row),'sources':json.loads(row['sources']),'supersedes':json.loads(row['supersedes'])})

    def _insert(self,topic,claim,value,written_by,status,sources=(),supersedes=(),checked_at=None):
        entry=Entry(id=str(uuid.uuid4()),topic=_norm(topic),claim=claim,value=str(value),written_by=written_by,status=status,sources=list(sources),supersedes=list(supersedes),created=time.time(),checked_at=checked_at)
        self.db.execute('INSERT INTO brain_entries VALUES (?,?,?,?,?,?,?,?,?,?)',(entry.id,entry.topic,entry.claim,entry.value,entry.written_by,entry.status,json.dumps([s.model_dump() for s in entry.sources]),json.dumps(entry.supersedes),entry.created,entry.checked_at))
        return entry

    def write(self,topic,claim,value,written_by):
        """Returns the new entry, or a Conflict when it disagrees with live memory."""
        rows=self.db.execute("SELECT * FROM brain_entries WHERE topic=? AND status IN ('active','disputed')",(_norm(topic),)).fetchall()
        live=[self._entry(r) for r in rows]
        if any(_norm(e.value)==_norm(value) for e in live):
            return next(e for e in live if _norm(e.value)==_norm(value))
        if not live:
            entry=self._insert(topic,claim,value,written_by,'active');self.db.commit();return entry
        entry=self._insert(topic,claim,value,written_by,'disputed')
        self.db.executemany("UPDATE brain_entries SET status='disputed' WHERE id=?",[(e.id,) for e in live])
        self.db.commit()
        return Conflict(topic=_norm(topic),entries=[*[e.model_copy(update={'status':'disputed'}) for e in live],entry])

    def read(self,topic=None):
        """What an agent sees before working: active entries only."""
        if topic is None:rows=self.db.execute("SELECT * FROM brain_entries WHERE status='active' ORDER BY created").fetchall()
        else:rows=self.db.execute("SELECT * FROM brain_entries WHERE status='active' AND topic=?",(_norm(topic),)).fetchall()
        return [self._entry(r) for r in rows]

    def conflicts(self):
        rows=self.db.execute("SELECT * FROM brain_entries WHERE status='disputed' ORDER BY created").fetchall()
        grouped={}
        for row in rows:grouped.setdefault(row['topic'],[]).append(self._entry(row))
        return [Conflict(topic=t,entries=e) for t,e in grouped.items()]

    def history(self,topic):
        return [self._entry(r) for r in self.db.execute('SELECT * FROM brain_entries WHERE topic=? ORDER BY created',(_norm(topic),)).fetchall()]

    def resolve(self,conflict,verdict,record):
        """Applies an arbiter verdict atomically; unresolved conflicts stay disputed for a human."""
        ids=[e.id for e in conflict.entries]
        winner=None
        with self.db:
            if verdict['outcome']=='resolved':
                chosen=next(e for e in conflict.entries if e.id==verdict['winner_id'])
                self.db.executemany("UPDATE brain_entries SET status='superseded' WHERE id=?",[(i,) for i in ids])
                winner=self._insert(conflict.topic,chosen.claim,chosen.value,'arbiter','active',[Source(**s) for s in verdict['sources']],ids,time.time())
            self.db.execute('INSERT INTO brain_arbitrations VALUES (?,?,?,?,?)',(str(uuid.uuid4()),conflict.topic,verdict['outcome'],json.dumps(record,allow_nan=False),time.time()))
        return winner

    def arbitrations(self):
        return [{**dict(r),'record':json.loads(r['record'])} for r in self.db.execute('SELECT * FROM brain_arbitrations ORDER BY created').fetchall()]
