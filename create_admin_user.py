from sqlalchemy.orm import Session
from database import SessionLocal
import models
from auth_utils import hash_password


def create_admin():
    db = SessionLocal()
    try:
        username = "admin"
        email = "admin@sounduk.ru"
        password = "6MOilsD3IgTZUKVVEqUxLg"

        existing_user = db.query(models.User).filter(models.User.email == email).first()

        if existing_user:
            print(f"Admin with email '{email}' already exists. Promoting + resetting password...")
            existing_user.is_admin = True
            existing_user.is_premium = True
            existing_user.is_verified = True
            existing_user.hashed_password = hash_password(password)
            db.commit()
            print(f"Admin '{email}' updated successfully.")
        else:
            print(f"Creating admin user '{email}'...")
            new_user = models.User(
                username=username,
                email=email,
                hashed_password=hash_password(password),
                is_admin=True,
                is_premium=True,
                is_verified=True,
            )
            db.add(new_user)
            db.commit()
            print(f"Admin '{email}' created successfully. Password: {password}")

    except Exception as e:
        print(f"Error creating admin: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
