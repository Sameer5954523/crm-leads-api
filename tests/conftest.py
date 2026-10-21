import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Role, User
from app.security import hash_password

# Uses PostgreSQL when TEST_DATABASE_URL is set (as in CI), otherwise a fast in-memory SQLite DB.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    engine = create_engine(TEST_DATABASE_URL)
else:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, email: str, role: Role, password: str = "password123", name: str | None = None) -> User:
    user = User(email=email, full_name=name or email.split("@")[0].title(), hashed_password=hash_password(password), role=role)
    db.add(user)
    db.commit()
    return user


def auth_header(client, email: str, password: str = "password123") -> dict:
    res = client.post("/auth/token", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def admin(db, client):
    make_user(db, "admin@example.com", Role.admin)
    return auth_header(client, "admin@example.com")


@pytest.fixture()
def manager(db, client):
    make_user(db, "manager@example.com", Role.manager)
    return auth_header(client, "manager@example.com")
