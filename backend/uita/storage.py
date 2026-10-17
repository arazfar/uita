"""Single-process modular monolith; database CAS also rejects cross-process stale writes."""
import os, time, uuid
from contextlib import contextmanager
from sqlalchemy import create_engine, Column, String, Integer, JSON, Float, select, update
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):pass
class Record(Base):
    __tablename__='records'
    id=Column(String(128),primary_key=True)
    kind=Column(String(40),index=True,nullable=False)
    version=Column(Integer,nullable=False,default=1)
    payload=Column(JSON,nullable=False)
    created_at=Column(Float,nullable=False,default=time.time)

class Store:
    def __init__(self,url=None,recover=False):
        url=url or os.environ.get('DATABASE_URL','sqlite:///./uita.db')
        self.engine=create_engine(url,connect_args={'check_same_thread':False} if url.startswith('sqlite') else {},pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        with self.transaction() as db:
            schema=db.get(Record,'schema-version')
            if not schema:db.add(Record(id='schema-version',kind='schema',payload={'version':2}))
            elif schema.payload.get('version',1)<2:schema.payload={'version':2,'migration':'Additive agent job journal; legacy payloads retained'}
            for r in db.scalars(select(Record).where(Record.kind=='job')) if recover else []:
                if r.payload['status'] in ('queued','running'):
                    r.payload={**r.payload,'status':'interrupted','stage':'interrupted','error':'Worker stopped before completion. Start a fresh bounded experiment.'}
    @contextmanager
    def transaction(self):
        with self.sessions.begin() as db:yield db
    def get(self,id,db=None):
        if db is not None:
            r=db.get(Record,id);return r.payload if r else None
        with self.sessions() as s:return self.get(id,s)
    def put(self,id,kind,payload,db=None):
        if db is None:
            with self.transaction() as s:return self.put(id,kind,payload,s)
        r=db.get(Record,id)
        if r:r.payload=payload;r.version+=1
        else:db.add(Record(id=id,kind=kind,payload=payload))
    def list(self,kind,limit=100):
        with self.sessions() as db:return [r.payload for r in db.scalars(select(Record).where(Record.kind==kind).order_by(Record.created_at.desc()).limit(limit))]
    def cas_state(self,old_version,payload,db):
        result=db.execute(update(Record).where(Record.id=='state',Record.version==old_version).values(payload=payload,version=old_version+1))
        if result.rowcount!=1:raise ValueError('Concurrent state update; refresh and retry')
