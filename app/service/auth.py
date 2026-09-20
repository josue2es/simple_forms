"""API key management and verification."""

import hashlib
import secrets
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..config import settings
from ..models import ApiKey


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return "sfk_" + secrets.token_urlsafe(24)


def verify_api_key(session: Session, key: str) -> bool:
    """Return True if the key is the master key or an active database key.

    Database keys are looked up by hash; last_used_at is stamped so unused
    keys are visible (and revocable) in the admin UI.
    """
    if not key:
        return False
    if settings.master_api_key and secrets.compare_digest(key, settings.master_api_key):
        return True
    db_key = session.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(key))).first()
    if not (db_key and db_key.active):
        return False
    db_key.last_used_at = utcnow()
    session.add(db_key)
    session.commit()
    return True


def create_api_key(session: Session, name: str) -> tuple[ApiKey, str]:
    """Create a new API key. Returns (db_object, plaintext_key)."""
    plaintext = generate_api_key()
    db_key = ApiKey(name=(name or "").strip() or "unnamed", key_hash=hash_key(plaintext))
    session.add(db_key)
    session.commit()
    session.refresh(db_key)
    return db_key, plaintext


def list_api_keys(session: Session) -> list[ApiKey]:
    return list(session.exec(select(ApiKey).order_by(ApiKey.created_at.desc())))


def revoke_api_key(session: Session, key_id: int) -> bool:
    db_key = session.get(ApiKey, key_id)
    if db_key is None:
        return False
    db_key.active = False
    session.add(db_key)
    session.commit()
    return True
