from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import Business, BusinessAccessToken, User


def _create_business(name="Biz", slug="biz"):
    business = Business(
        name=name,
        slug=slug,
        owner_name="Owner",
        email=f"{slug}@example.com",
        status="active",
    )
    db.session.add(business)
    db.session.flush()
    return business


def _create_user(email, role, business_id, password="pass-123"):
    user = User(
        business_id=business_id,
        full_name=email.split("@")[0],
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        status="active",
    )
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, email, password="pass-123"):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.get_json()["access_token"]


def test_role_enforcement_on_user_creation_endpoints():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()

        b1 = _create_business("B1", "b1")
        _create_user("super@example.com", "superuser", b1.id)
        _create_user("stuff@example.com", "stuff", b1.id)
        db.session.commit()

    client = app.test_client()

    stuff_token = _login(client, "stuff@example.com")
    deny_resp = client.post(
        "/api/auth/users/stuff",
        json={"full_name": "X", "email": "x@example.com", "password": "pass-123"},
        headers={"Authorization": f"Bearer {stuff_token}"},
    )
    assert deny_resp.status_code == 403

    super_token = _login(client, "super@example.com")
    ok_resp = client.post(
        "/api/auth/users/stuff",
        json={"full_name": "New Stuff", "email": "newstuff@example.com", "password": "pass-123", "business_id": b1.id},
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert ok_resp.status_code == 201
    assert ok_resp.get_json()["user"]["role"] == "stuff"


def test_access_token_only_endpoint_rejects_jwt_and_checks_scopes():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()

        b1 = _create_business("B1", "b1")
        stuff = _create_user("stuff@example.com", "stuff", b1.id)
        db.session.commit()
        stuff_id = stuff.id
        business_id = b1.id

    client = app.test_client()
    jwt_token = _login(client, "stuff@example.com")

    jwt_reject = client.post(
        "/api/internal/flow/resolve-next",
        json={"node": "a"},
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert jwt_reject.status_code == 403

    with app.app_context():
        token_model = BusinessAccessToken(
            business_id=business_id,
            name="limited",
            token_prefix="dialyra_live_test",
            token_hash=__import__("hashlib").sha256("raw-token-1".encode()).hexdigest(),
            scopes='["calls:read"]',
            is_active=True,
            expires_at=datetime.utcnow() + timedelta(days=1),
            created_by=stuff_id,
        )
        db.session.add(token_model)
        db.session.commit()

    missing_scope = client.post(
        "/api/internal/flow/resolve-next",
        json={"node": "a"},
        headers={"X-Dialyra-Access-Token": "raw-token-1"},
    )
    assert missing_scope.status_code == 403

    with app.app_context():
        token_model = BusinessAccessToken.query.filter_by(name="limited").first()
        token_model.scopes = '["calls:read", "flow:resolve"]'
        db.session.commit()

    allowed = client.post(
        "/api/internal/flow/resolve-next",
        json={"node": "a"},
        headers={"X-Dialyra-Access-Token": "raw-token-1"},
    )
    assert allowed.status_code == 200
    body = allowed.get_json()
    assert body["business_id"] == business_id


def test_login_rate_limit_blocks_after_repeated_failures():
    app = create_app("testing")
    app.config["LOGIN_MAX_FAILED_ATTEMPTS"] = 2
    app.config["LOGIN_RATE_LIMIT_WINDOW_MINUTES"] = 15

    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        _create_user("u@example.com", "general", b1.id, password="good-pass")
        db.session.commit()

    client = app.test_client()

    r1 = client.post("/api/auth/login", json={"email": "u@example.com", "password": "bad"})
    r2 = client.post("/api/auth/login", json={"email": "u@example.com", "password": "bad"})
    r3 = client.post("/api/auth/login", json={"email": "u@example.com", "password": "good-pass"})

    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 401
    assert "Too many failed attempts" in r3.get_json()["error"]
