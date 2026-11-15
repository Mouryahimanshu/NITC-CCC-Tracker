"""Create the SQL schema, seed T1–T6, and provision optional first accounts."""

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Room, User
from app.db.postgres import create_schema, dispose_database, initialize_database, session_scope
from app.services.auth import hash_password


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in backend/.env before bootstrapping.")
    initialize_database()
    try:
        create_schema()
        with session_scope() as db:
            for code in ("T1", "T2", "T3", "T4", "T5", "T6"):
                if db.scalar(select(Room).where(Room.code == code)) is None:
                    db.add(Room(code=code, active=True))
            username = settings.bootstrap_admin_username.strip().lower()
            password = settings.bootstrap_admin_password
            accounts = [
                (username, "CCC Administrator", password, "ADMIN"),
                (settings.bootstrap_faculty_username.strip().lower(),
                 settings.bootstrap_faculty_display_name.strip(), settings.bootstrap_faculty_password, "FACULTY"),
            ]
            for account_username, display_name, account_password, role in accounts:
                if not account_username or not account_password:
                    continue
                if len(account_password) < 12:
                    raise SystemExit(f"Bootstrap password for {role} must be at least 12 characters.")
                if db.scalar(select(User).where(User.username == account_username)) is None:
                    db.add(User(username=account_username, display_name=display_name,
                                password_hash=hash_password(account_password), role=role, active=True))
                    print(f"Initial {role.lower()} account created.")
            if not password:
                print("No administrator created; set BOOTSTRAP_ADMIN_PASSWORD to create one.")
            db.commit()
            print("PostgreSQL schema ready; rooms T1–T6 ensured.")
    finally:
        dispose_database()


if __name__ == "__main__":
    main()
