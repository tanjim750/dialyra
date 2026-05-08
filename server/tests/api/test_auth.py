from app import create_app
from app.extensions import db


def test_register_login_me_refresh_logout_flow():
    app = create_app("testing")

    with app.app_context():
        db.drop_all()
        db.create_all()

    client = app.test_client()

    register_payload = {
        "business_name": "ABC Store",
        "owner_name": "Tanjim",
        "email": "owner@example.com",
        "phone": "+880100000000",
        "password": "secret-123",
    }

    reg_resp = client.post("/api/auth/register", json=register_payload)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.get_json()
    assert reg_data["user"]["role"] == "general"
    assert reg_data["access_token"]
    assert reg_data["refresh_token"]

    login_resp = client.post(
        "/api/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.get_json()

    me_resp = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login_data['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.get_json()["user"]["email"] == register_payload["email"]

    refresh_resp = client.post(
        "/api/auth/refresh", json={"refresh_token": login_data["refresh_token"]}
    )
    assert refresh_resp.status_code == 200
    refresh_data = refresh_resp.get_json()
    assert refresh_data["access_token"]
    assert refresh_data["refresh_token"]

    logout_resp = client.post(
        "/api/auth/logout", json={"refresh_token": refresh_data["refresh_token"]}
    )
    assert logout_resp.status_code == 200
    assert logout_resp.get_json()["message"] == "Logout successful"


def test_stuff_can_create_general_user():
    app = create_app("testing")

    with app.app_context():
        db.drop_all()
        db.create_all()

    client = app.test_client()

    register_payload = {
        "business_name": "ABC Store",
        "owner_name": "Tanjim",
        "email": "owner@example.com",
        "phone": "+880100000000",
        "password": "secret-123",
        "role": "stuff",
    }
    reg_resp = client.post("/api/auth/register", json=register_payload)
    token = reg_resp.get_json()["access_token"]

    create_resp = client.post(
        "/api/auth/users",
        json={
            "full_name": "General User",
            "email": "general@example.com",
            "password": "secret-456",
            "role": "general",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert create_resp.status_code == 201
    body = create_resp.get_json()
    assert body["user"]["role"] == "general"
