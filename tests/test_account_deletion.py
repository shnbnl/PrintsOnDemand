"""Account deletion, ownership boundaries, private bytes, and rollback."""

from decimal import Decimal
from pathlib import Path

import pytest
from flask import g
from sqlalchemy import select

from app.extensions import db
from app.models import (
    ColorMode, Order, OrderDestination, OrderItem, PaperSize, Payment, PaymentMethod,
    PaymentStatus, PrintConfiguration, Professor, UploadedFile, User, UserRole,
)
from app.services import account_deletion
from app.storage import LocalStorage, StagedDeletion
from test_auth import csrf_token, login
from test_orders import approved_professor, file, shop, sign_in, student


def customer_graph(app, role):
    owner_email = "maria.santos@example.edu" if role == UserRole.PROFESSOR else "owner@example.edu"
    owner_id = student(app, owner_email, role=role)
    survivor_id = student(app, "survivor@example.edu")
    staff_id = student(app, "staff@example.edu", role=UserRole.SHOP_STAFF)
    admin_id = student(app, "admin@example.edu", role=UserRole.ADMIN)
    shop_id = shop(app, name="Blue and Silver Bookstore")
    professor_id = approved_professor(app, faculty="CCIS")
    owner_file_id = file(app, owner_id, name="owner-private.pdf")
    extra_file_id = file(app, owner_id, name="owner-second.pdf")
    survivor_file_id = file(app, survivor_id, name="survivor-private.pdf")
    with app.app_context():
        if role == UserRole.PROFESSOR:
            db.session.get(User, owner_id).professor_id = professor_id
        owner_order = Order(
            user_id=owner_id, shop_id=shop_id, shop_name="Blue and Silver Bookstore",
            order_reference="POD-OWNER", destination=OrderDestination.PROFESSOR,
            professor_id=professor_id, professor_name="Maria Santos",
            professor_email="maria.santos@example.edu", professor_faculty="CCIS",
            subtotal=Decimal("2.25"), rush_fee=Decimal("0"), fees_total=Decimal("0"),
            total=Decimal("2.25"), currency="PHP",
        )
        other_order = Order(
            user_id=survivor_id, shop_id=shop_id, shop_name="Blue and Silver Bookstore",
            order_reference="POD-SURVIVOR", destination=OrderDestination.PROFESSOR,
            professor_id=professor_id, professor_name="Maria Santos",
            professor_email="maria.santos@example.edu", professor_faculty="CCIS",
            subtotal=Decimal("2.25"), rush_fee=Decimal("0"), fees_total=Decimal("0"),
            total=Decimal("2.25"), currency="PHP",
        )
        for order, file_id in ((owner_order, owner_file_id), (other_order, survivor_file_id)):
            order.items.append(OrderItem(
                uploaded_file_id=file_id, original_filename="private.pdf",
                paper_size=PaperSize.A4, color_mode=ColorMode.GRAYSCALE,
                quantity=1, is_rush=False, unit_price=Decimal("2.25"),
                line_total=Decimal("2.25"),
            ))
            order.payment = Payment(
                payment_method=PaymentMethod.ONLINE, payment_status=PaymentStatus.SUBMITTED,
                amount=Decimal("2.25"), currency="PHP", payment_reference="PRIVATE-REF-1234",
                reviewed_by_id=staff_id,
            )
            db.session.add(order)
        db.session.commit()
        keys = {record.id: record.storage_key for record in db.session.scalars(select(UploadedFile))}
    return {
        "owner": owner_id, "survivor": survivor_id, "staff": staff_id, "admin": admin_id,
        "shop": shop_id, "professor": professor_id,
        "owner_files": (owner_file_id, extra_file_id), "survivor_file": survivor_file_id,
        "keys": keys,
    }


def delete_request(client, **changes):
    token = csrf_token(client.get("/account/delete"))
    values = {"csrf_token": token, "password": "A-strong-password-123", "confirm": "y"}
    values.update(changes)
    return client.post("/account/delete", data=values)


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
def test_confirmed_deletion_removes_exact_owned_graph_and_bytes(client, test_app, role):
    graph = customer_graph(test_app, role)
    storage = Path(test_app.config["UPLOAD_STORAGE_ROOT"])
    sign_in(client, graph["owner"])
    assert client.get("/account").status_code == 200
    confirmation = client.get("/account/delete")
    assert confirmation.status_code == 200 and b"cannot be undone" in confirmation.data
    assert client.get("/account/delete").status_code == 200  # GET is read-only.
    assert client.get("/account").status_code == 200
    response = delete_request(client, user_id=str(graph["staff"]))
    assert response.status_code == 302 and response.headers["Location"].endswith("/")
    assert b"permanently deleted" in client.get("/").data
    assert client.get("/account").status_code == 302
    assert client.get("/files").status_code == 302
    # The fixture keeps one app context across requests; clear its CSRF cache
    # after the route has deliberately cleared the session.
    g.pop("csrf_token", None)
    denied_login = login(client, "maria.santos@example.edu" if role == UserRole.PROFESSOR else "owner@example.edu")
    assert denied_login.status_code == 200, denied_login.data[:500]
    with test_app.app_context():
        assert db.session.get(User, graph["owner"]) is None
        assert {record.id for record in db.session.scalars(select(UploadedFile))} == {graph["survivor_file"]}
        assert {record.file_id for record in db.session.scalars(select(PrintConfiguration))} == {graph["survivor_file"]}
        assert [order.order_reference for order in db.session.scalars(select(Order))] == ["POD-SURVIVOR"]
        assert len(db.session.scalars(select(OrderItem)).all()) == 1
        assert len(db.session.scalars(select(Payment)).all()) == 1
        assert db.session.get(User, graph["survivor"]) is not None
        assert db.session.get(User, graph["staff"]) is not None
        assert db.session.get(User, graph["admin"]) is not None
        profile = db.session.get(Professor, graph["professor"])
        assert profile is not None
        assert profile.account is None
        assert profile.accepts_student_deliveries is (role != UserRole.PROFESSOR)
        assert db.session.get(Order, 2).professor_id == profile.id
    assert all(not (storage / graph["keys"][file_id]).exists() for file_id in graph["owner_files"])
    assert (storage / graph["keys"][graph["survivor_file"]]).exists()
    assert not list(storage.glob(".account-deletion-*"))
    assert login(client, "survivor@example.edu").status_code == 302


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
def test_account_confirmation_and_password_are_required(client, test_app, role):
    owner_id = student(test_app, f"{role.value.lower()}@example.edu", role=role)
    sign_in(client, owner_id)
    assert delete_request(client, confirm="").status_code == 400
    assert delete_request(client, password="").status_code == 400
    assert delete_request(client, password="incorrect").status_code == 400
    with test_app.app_context():
        assert db.session.get(User, owner_id) is not None


def test_unauthenticated_and_privileged_users_cannot_delete(client, test_app):
    assert client.get("/account").status_code == 302
    assert client.get("/account/delete").status_code == 302
    assert client.post("/account/delete", data={"password": "x", "confirm": "y"}).status_code == 400
    for role in (UserRole.SHOP_STAFF, UserRole.ADMIN):
        user_id = student(test_app, f"{role.value.lower()}@example.edu", role=role)
        sign_in(client, user_id)
        assert client.get("/account").status_code == 403
        assert client.get("/account/delete").status_code == 403
        home = client.get("/shop" if role == UserRole.SHOP_STAFF else "/admin")
        token = csrf_token(home)
        assert client.post("/account/delete", data={
            "csrf_token": token, "password": "A-strong-password-123", "confirm": "y",
        }).status_code == 403
        with test_app.app_context():
            assert db.session.get(User, user_id) is not None


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
def test_csrf_and_forged_ids_cannot_delete_other_accounts(client, test_app, role):
    owner = student(test_app, "owner@example.edu", role=role)
    other = student(test_app, "other@example.edu", role=role)
    staff = student(test_app, "staff@example.edu", UserRole.SHOP_STAFF)
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    sign_in(client, owner)
    assert client.post("/account/delete", data={"password": "A-strong-password-123", "confirm": "y"}).status_code == 400
    assert client.post("/account/delete", data={"csrf_token": "invalid", "password": "A-strong-password-123", "confirm": "y"}).status_code == 400
    for target in (other, staff, admin):
        assert client.get(f"/account/{target}/delete").status_code == 404
        assert client.post(f"/account/{target}/delete").status_code == 404
    assert delete_request(client, user_id=str(other), target_user_id=str(staff)).status_code == 302
    with test_app.app_context():
        assert db.session.get(User, owner) is None
        assert all(db.session.get(User, target) is not None for target in (other, staff, admin))


def test_remember_cookie_is_cleared_after_deletion(client, test_app):
    owner = student(test_app, "owner@example.edu")
    token = csrf_token(client.get("/auth/login"))
    response = client.post("/auth/login", data={
        "csrf_token": token, "email": "owner@example.edu",
        "password": "A-strong-password-123", "remember_me": "y",
    })
    assert response.status_code == 302
    assert client.get_cookie("remember_token") is not None
    assert delete_request(client).status_code == 302
    assert client.get_cookie("remember_token") is None
    assert client.get("/account").status_code == 302
    with test_app.app_context():
        assert db.session.get(User, owner) is None


def test_unlinked_account_without_uploads_can_be_deleted(client, test_app):
    owner = student(test_app, "professor@example.edu", role=UserRole.PROFESSOR)
    test_app.config["STORAGE_BACKEND"] = "unavailable"
    sign_in(client, owner)
    assert delete_request(client).status_code == 302
    with test_app.app_context():
        assert db.session.get(User, owner) is None


def test_existing_private_upload_is_removed_when_production_uploads_are_disabled(client, test_app):
    owner = student(test_app, "owner@example.edu")
    file_id = file(test_app, owner)
    with test_app.app_context():
        key = db.session.get(UploadedFile, file_id).storage_key
    path = Path(test_app.config["UPLOAD_STORAGE_ROOT"]) / key
    assert path.exists()
    test_app.config["ENV_NAME"] = "production"
    sign_in(client, owner)
    assert delete_request(client).status_code == 302
    assert not path.exists()
    with test_app.app_context():
        assert db.session.get(User, owner) is None


def test_external_payment_review_reference_is_unlinked_not_deleted(client, test_app):
    graph = customer_graph(test_app, UserRole.STUDENT)
    with test_app.app_context():
        db.session.scalar(select(Payment).join(Order).where(Order.user_id == graph["survivor"])).reviewed_by_id = graph["owner"]
        db.session.commit()
    sign_in(client, graph["owner"])
    assert delete_request(client).status_code == 302
    with test_app.app_context():
        survivor_payment = db.session.scalar(select(Payment))
        assert survivor_payment.order.user_id == graph["survivor"]
        assert survivor_payment.reviewed_by_id is None


def test_database_failure_restores_everything_including_private_bytes(client, test_app, monkeypatch):
    graph = customer_graph(test_app, UserRole.STUDENT)
    storage = Path(test_app.config["UPLOAD_STORAGE_ROOT"])
    sign_in(client, graph["owner"])
    def fail_commit():
        raise RuntimeError("simulated commit failure")
    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = delete_request(client)
    assert response.status_code == 503
    assert b"could not be completed" in response.data
    with test_app.app_context():
        assert db.session.get(User, graph["owner"]) is not None
        assert {record.order_reference for record in db.session.scalars(select(Order))} == {"POD-OWNER", "POD-SURVIVOR"}
        assert len(db.session.scalars(select(Payment)).all()) == 2
        assert len(db.session.scalars(select(UploadedFile)).all()) == 3
    assert all((storage / key).exists() for key in graph["keys"].values())
    assert not list(storage.glob(".account-deletion-*"))


def test_storage_failure_rolls_back_without_deleting_account(client, test_app, monkeypatch):
    graph = customer_graph(test_app, UserRole.STUDENT)
    sign_in(client, graph["owner"])
    def fail_stage(self, keys):
        raise OSError("simulated storage failure")
    monkeypatch.setattr(LocalStorage, "stage_deletion", fail_stage)
    assert delete_request(client).status_code == 503
    with test_app.app_context():
        assert db.session.get(User, graph["owner"]).is_active
        assert db.session.scalar(select(Order).where(Order.user_id == graph["owner"])) is not None


def test_partial_staging_failure_restores_first_moved_file(client, test_app, monkeypatch):
    graph = customer_graph(test_app, UserRole.STUDENT)
    sign_in(client, graph["owner"])
    storage = Path(test_app.config["UPLOAD_STORAGE_ROOT"])
    original_replace = Path.replace
    failed_key = graph["keys"][graph["owner_files"][1]]

    def fail_second_move(source, destination):
        if source.name == failed_key and source.parent == storage:
            raise OSError("simulated second move failure")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second_move)
    assert delete_request(client).status_code == 503
    assert all((storage / key).exists() for key in graph["keys"].values())
    assert not list(storage.glob(".account-deletion-*"))
    with test_app.app_context():
        assert db.session.get(User, graph["owner"]).is_active


def test_purge_failure_is_recoverable_without_restoring_deleted_account(client, test_app, monkeypatch):
    graph = customer_graph(test_app, UserRole.STUDENT)
    sign_in(client, graph["owner"])
    storage = Path(test_app.config["UPLOAD_STORAGE_ROOT"])

    def fail_purge(self):
        raise OSError("simulated post-commit cleanup failure")

    monkeypatch.setattr(StagedDeletion, "purge", fail_purge)
    assert delete_request(client).status_code == 503
    with test_app.app_context():
        assert db.session.get(User, graph["owner"]) is None
        assert db.session.get(User, graph["survivor"]) is not None
    assert len(list(storage.glob(".account-deletion-*"))) == 1
    runner = test_app.test_cli_runner()
    recovered = runner.invoke(args=["recover-account-deletions"])
    assert recovered.exit_code == 0, recovered.output
    assert "removed 2 unreferenced uploads" in recovered.output
    assert not list(storage.glob(".account-deletion-*"))
    assert (storage / graph["keys"][graph["survivor_file"]]).exists()


def test_recovery_restores_bytes_when_metadata_transaction_rolled_back(test_app):
    user_id = student(test_app, "owner@example.edu")
    file_id = file(test_app, user_id)
    storage = Path(test_app.config["UPLOAD_STORAGE_ROOT"])
    with test_app.app_context():
        key = db.session.get(UploadedFile, file_id).storage_key
        staged = LocalStorage(storage, test_app.static_folder).stage_deletion([key])
        assert not (storage / key).exists()
        assert staged.directory is not None
    runner = test_app.test_cli_runner()
    recovered = runner.invoke(args=["recover-account-deletions"])
    assert recovered.exit_code == 0, recovered.output
    assert "Restored 1 referenced uploads" in recovered.output
    assert (storage / key).exists()

