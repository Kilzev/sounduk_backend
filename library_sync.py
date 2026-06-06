"""Increment user library_revision on library mutations."""
from sqlalchemy.orm import Session

import models


def bump_library_revision(db: Session, user_id: int) -> int:
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .with_for_update()
        .first()
    )
    if user is None:
        raise ValueError(f"User {user_id} not found")
    user.library_revision = (user.library_revision or 0) + 1
    db.commit()
    db.refresh(user)
    return user.library_revision


def current_library_revision(db: Session, user_id: int) -> int:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        return 1
    return user.library_revision or 1
