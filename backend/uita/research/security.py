"""Opaque database sessions; no API key is sent to the browser."""

import hashlib
import secrets
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import delete, select

from .database import Session, User

HASHER = PasswordHasher()
DUMMY = HASHER.hash("not-a-user-password")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def add_user(db, username, password, team="research", role="operator"):
    if role not in ("viewer", "operator", "administrator") or len(password) < 12:
        raise ValueError("Use a valid role and a password of at least 12 characters")
    if db.scalar(select(User).where(User.username == username)):
        raise ValueError("Account already exists")
    user = User(
        id=str(uuid.uuid4()),
        team=team,
        username=username,
        password_hash=HASHER.hash(password),
        role=role,
    )
    db.add(user)
    return user


def login(db, username, password):
    user = db.scalar(select(User).where(User.username == username))
    try:
        HASHER.verify(user.password_hash if user else DUMMY, password)
    except VerificationError:
        return None
    if not user or not user.enabled:
        return None
    if HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = HASHER.hash(password)
    token = secrets.token_urlsafe(48)
    db.add(
        Session(
            token_hash=token_hash(token), user_id=user.id, expires=time.time() + 43200
        )
    )
    return token


def authenticate(db, token):
    if not token:
        return None
    session = db.get(Session, token_hash(token))
    if not session or session.expires <= time.time():
        return None
    user = db.get(User, session.user_id)
    return user if user and user.enabled else None


def logout(db, token):
    db.execute(delete(Session).where(Session.token_hash == token_hash(token or "")))
