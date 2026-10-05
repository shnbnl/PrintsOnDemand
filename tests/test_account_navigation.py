"""Customer identity navigation and retired professor page behavior."""

import re

import pytest

from app.models import UserRole
from test_orders import sign_in, student, token


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
def test_account_action_is_grouped_with_identity(client, test_app, role):
    user_id = student(test_app, f"{role.value.lower()}@example.edu", role)
    sign_in(client, user_id)
    page = client.get("/account")
    assert page.status_code == 200
    groups = re.findall(rb'<div class="nav-identity"[^>]*>.*?</div>', page.data, re.S)
    assert len(groups) == 2  # Desktop and mobile navigation.
    for group in groups:
        assert role.value.title().encode() in group
        assert b'href="/account"' in group
        assert b">Account</a>" in group
    assert b'id="account-identity"' in page.data
    assert b'href="/account/delete"' in page.data
    assert client.get("/account").status_code == 200
    assert b'/professor/settings' not in page.data


def test_retired_professor_page_redirects_and_preference_is_csrf_protected(client, test_app):
    user_id = student(test_app, "professor@example.edu", UserRole.PROFESSOR)
    sign_in(client, user_id)
    legacy = client.get("/professor/settings")
    assert legacy.status_code == 302 and legacy.headers["Location"].endswith("/account")
    assert client.post("/professor/settings", data={"accepts_student_deliveries": "y"}).status_code == 405
    account = client.get("/account")
    assert b"Verification" in account.data
    assert b"Student print deliveries" in account.data
    assert client.post("/account/professor-preference", data={
        "department": "CCIS", "accepts_student_deliveries": "y",
    }).status_code == 400
    assert client.post("/account/professor-preference", data={
        "csrf_token": token(account), "department": "CCIS",
        "accepts_student_deliveries": "y",
    }).status_code == 302
