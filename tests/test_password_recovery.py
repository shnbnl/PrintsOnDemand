"""Local-only password recovery and profile regressions."""

from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select

from app.extensions import db
from app.models import PasswordResetGrant, User
from app.services.password_reset import now_utc
from test_auth import PASSWORD, add_user, csrf_token, login
from test_orders import shop


def request_link(client, email):
    return client.post("/auth/forgot-password", data={
        "csrf_token": csrf_token(client.get("/auth/forgot-password")), "email": email,
    }, follow_redirects=True)


def test_password_reset_one_use_and_non_enumerating(client, test_app, monkeypatch):
    add_user(test_app)
    test_app.config.update(MAIL_HOST="smtp.invalid", MAIL_FROM="test@example.invalid",
                           PASSWORD_RESET_BASE_URL="http://localhost")
    delivered = []
    monkeypatch.setattr("app.services.password_reset.send_reset_email",
                        lambda address, link: delivered.append((address, link)))
    unknown = request_link(client, "unknown@example.com")
    known = request_link(client, "student@example.com")
    assert unknown.status_code == known.status_code == 200
    assert b"If this is an active student or professor account" in unknown.data
    assert b"If this is an active student or professor account" in known.data
    assert len(delivered) == 1
    path = urlsplit(delivered[0][1]).path
    assert client.get(path).status_code == 200
    new_password = "Another-long-password-456"
    response = client.post(path, data={
        "csrf_token": csrf_token(client.get(path)), "password": new_password,
        "confirm_password": new_password,
    })
    assert response.status_code == 302
    assert client.get(path).status_code == 400
    assert login(client, password=PASSWORD).status_code == 200
    assert login(client, password=new_password).status_code == 302


def test_reset_expiry_throttle_and_missing_delivery(client, test_app, monkeypatch):
    add_user(test_app)
    assert request_link(client, "student@example.com").status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(PasswordResetGrant)) is None
    test_app.config.update(MAIL_HOST="smtp.invalid", MAIL_FROM="test@example.invalid",
                           PASSWORD_RESET_BASE_URL="http://localhost")
    delivered = []
    monkeypatch.setattr("app.services.password_reset.send_reset_email",
                        lambda address, link: delivered.append(link))
    for _ in range(4):
        assert request_link(client, "student@example.com").status_code == 200
    assert len(delivered) == 2  # The earlier request counts toward the hourly limit.
    path = urlsplit(delivered[0]).path
    with test_app.app_context():
        grant = db.session.scalar(select(PasswordResetGrant).order_by(PasswordResetGrant.id))
        grant.expires_at = now_utc() - timedelta(seconds=1)
        db.session.commit()
    assert client.get(path).status_code == 400


def test_profile_name_edit_keeps_email_and_role(client, test_app):
    user_id = add_user(test_app)
    assert login(client).status_code == 302
    response = client.post("/account/profile", data={
        "csrf_token": csrf_token(client.get("/account")), "name": "  New Name  ",
    })
    assert response.status_code == 302
    with test_app.app_context():
        user = db.session.get(User, user_id)
        assert user.name == "New Name"
        assert user.email == "student@example.com"
        assert user.check_password(PASSWORD)


def test_philippine_time_filter_does_not_reinterpret_naive_utc(test_app):
    from datetime import datetime, timezone

    with test_app.app_context():
        render = test_app.jinja_env.filters["pht_datetime"]
        expected = "Oct 6, 2026, 1:13 AM PHT"
        assert render(datetime(2026, 10, 5, 17, 13)) == expected
        assert render(datetime(2026, 10, 5, 17, 13, tzinfo=timezone.utc)) == expected


def test_public_shop_preview_shows_only_active_shop_information(client, test_app):
    shop(test_app, name="Public shop")
    shop(test_app, name="Private inactive shop", active=False)
    response = client.get("/shops/preview")
    assert response.status_code == 200
    assert b"Public shop" in response.data
    assert b"Private inactive shop" not in response.data
    assert b"Campus Road" in response.data
    assert b"order_reference" not in response.data
