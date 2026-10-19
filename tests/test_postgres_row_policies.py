"""Real PostgreSQL policy checks against an explicitly disposable, empty DB.

Set POSTGRES_RLS_TEST_URL to run; never point this at a deployed application DB.
The fixture refuses a database that already has any application tables.
"""

from contextlib import contextmanager
from decimal import Decimal
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from psycopg import ClientCursor
from flask import g
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import (ColorMode, Order, OrderDestination, OrderItem, OrderStatus,
    PaperSize, Payment, PaymentMethod, PaymentStatus, PrintingShop, Professor,
    ProfessorVerificationStatus, User, UserRole)
from test_orders import file, sign_in, student, token


def policy_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/d82f1b70a631_private_data_row_security.py"
    spec = importlib.util.spec_from_file_location("private_row_policies", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def postgres_app(monkeypatch, tmp_path):
    url = os.getenv("POSTGRES_RLS_TEST_URL")
    if not url:
        pytest.skip("Set POSTGRES_RLS_TEST_URL to an empty disposable PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "isolated-postgres-policy-tests-only-123")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setenv("PROXY_FIX_HOPS", "0")
    class PolicyTestingConfig(TestingConfig):
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"prepare_threshold": None, "cursor_factory": ClientCursor}}

    app = create_app(PolicyTestingConfig)
    app.config["UPLOAD_STORAGE_ROOT"] = str(tmp_path / "uploads")
    role = "pod_policy_test_" + uuid4().hex
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "postgresql":
            pytest.fail("PostgreSQL policy tests require PostgreSQL")
        if set(inspect(engine).get_table_names()) & set(db.metadata.tables):
            pytest.fail("Refusing to use a DB containing application tables; supply an empty disposable test DB")
        db.create_all()
        ids = seed(app)
        with engine.begin() as connection:
            connection.exec_driver_sql(policy_migration().POLICY_SQL)
            connection.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public, pod_security TO {role}")
            connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
            connection.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        db.session.remove()
        engine.dispose()

        def runtime_checkout(connection, record, proxy):
            cursor = connection.cursor()
            try:
                cursor.execute(f"SET ROLE {role}")
                connection.commit()
            finally:
                cursor.close()
        event.listen(engine, "checkout", runtime_checkout)

        @app.before_request
        def reset_test_caches():
            for key in ("_login_user", "csrf_token", "database_actor_id", "database_erasure_id",
                        "clear_site_data", "clear_browser_cookies"):
                g.pop(key, None)
        # The test holds an app context; real requests each get a fresh g.
        app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())
        @app.teardown_request
        def release_test_transaction(error):
            db.session.remove()

        try:
            yield app, ids
        finally:
            db.session.remove()
            event.remove(engine, "checkout", runtime_checkout)
            engine.dispose()
            # Connections are now fresh owner connections. Only fixture-created
            # objects are removed, after the initial empty-DB guard above.
            with engine.begin() as connection:
                connection.exec_driver_sql("RESET ROLE")
                connection.exec_driver_sql("DROP SCHEMA pod_security CASCADE")
            db.drop_all()
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE {role}")
            engine.dispose()


def seed(app):
    from datetime import time
    shops = [PrintingShop(name=name, address="Test Campus", opening_time=time(6, 30),
                         closing_time=time(17), is_active=True)
             for name in ("Blue and Silver Bookstore", "Other Test Shop")]
    db.session.add_all(shops)
    db.session.commit()
    users = {name: student(app, name + "@example.edu", role=role)
             for name, role in (("one", UserRole.STUDENT), ("two", UserRole.STUDENT),
                 ("professor", UserRole.PROFESSOR), ("blue", UserRole.SHOP_STAFF),
                 ("other", UserRole.SHOP_STAFF), ("admin", UserRole.ADMIN))}
    db.session.get(User, users["blue"]).shop_id = shops[0].id
    db.session.get(User, users["other"]).shop_id = shops[1].id
    profile = Professor(name="Policy Professor", email="professor@example.edu",
        department="MITL", faculty="Civil Engineering", is_active=True,
        direct_send_approved=True, accepts_student_deliveries=True)
    db.session.add(profile)
    db.session.flush()
    professor = db.session.get(User, users["professor"])
    professor.professor_id = profile.id
    professor.professor_department = "MITL"
    professor.professor_faculty = "Civil Engineering"
    professor.professor_verification_status = ProfessorVerificationStatus.VERIFIED
    db.session.commit()
    files = {name: file(app, users[owner], name=name + ".pdf") for name, owner in (
        ("one", "one"), ("two", "two"), ("private", "two"), ("professor", "professor"), ("staged", "one"))}
    order_ids, payment_ids = [], []
    for number, (owner, shop_index) in enumerate((("one", 0), ("two", 1), ("professor", 1), ("two", 0)), 1):
        order = Order(user_id=users[owner], shop_id=shops[shop_index].id,
            order_reference=f"POD-POLICY-{number}", shop_name=shops[shop_index].name,
            destination=OrderDestination.PICKUP, status=OrderStatus.PENDING_PAYMENT,
            subtotal=Decimal("2.25"), rush_fee=0, fees_total=0, total=Decimal("2.25"), currency="PHP")
        if number == 4:
            order.professor_id = profile.id
            order.professor_name = profile.name
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(order_id=order.id, uploaded_file_id=files[owner],
            original_filename=owner + ".pdf", paper_size=PaperSize.A4,
            color_mode=ColorMode.GRAYSCALE, quantity=1, is_rush=False,
            unit_price=Decimal("2.25"), line_total=Decimal("2.25")))
        payment = Payment(order_id=order.id, payment_method=PaymentMethod.ONSITE,
            payment_status=PaymentStatus.PENDING, amount=Decimal("2.25"), currency="PHP",
            reviewed_by_id=users["professor"] if number == 2 else None)
        db.session.add(payment)
        db.session.flush()
        order_ids.append(order.id)
        payment_ids.append(payment.id)
    db.session.commit()
    return {"users": users, "files": files, "orders": order_ids, "payments": payment_ids}


@contextmanager
def actor_transaction(app, user_id):
    with app.test_request_context("/"):
        g.database_actor_id = user_id
        with db.engine.begin() as connection:
            yield connection


def test_postgres_unfiltered_reads_and_pool_context_isolation(postgres_app):
    app, ids = postgres_app
    for name, expected in (("one", [1]), ("two", [2, 4]), ("blue", [1, 4]), ("other", [2, 3]), ("admin", [1, 2, 3, 4])):
        with actor_transaction(app, ids["users"][name]) as connection:
            orders = connection.execute(text("SELECT id FROM orders ORDER BY id")).scalars().all()
            assert orders == [ids["orders"][index - 1] for index in expected]
            payments = connection.execute(text("SELECT order_id FROM payments ORDER BY order_id")).scalars().all()
            assert payments == orders
    # Reused pooled connections outside a verified request are deny-by-default.
    with db.engine.begin() as connection:
        for table in ("orders", "order_items", "payments", "uploaded_files", "print_configurations"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_postgres_file_scope_cross_account_insert_and_immutable_snapshots(postgres_app):
    app, ids = postgres_app
    with actor_transaction(app, ids["users"]["blue"]) as connection:
        visible = connection.execute(text("SELECT id FROM uploaded_files ORDER BY id")).scalars().all()
        assert visible == sorted([ids["files"]["one"], ids["files"]["two"]])
        assert connection.execute(text("UPDATE uploaded_files SET original_filename='forged' RETURNING id")).all() == []
        assert connection.execute(text("UPDATE order_items SET quantity=2 RETURNING id")).all() == []
    # The same INSERT must succeed with the customer's own file; a blanket
    # rejection would pass the cross-account denial without proving usability.
    with actor_transaction(app, ids["users"]["one"]) as connection:
        inserted = connection.execute(text("""
          INSERT INTO order_items (order_id,uploaded_file_id,original_filename,paper_size,color_mode,
            quantity,is_rush,unit_price,line_total,created_at,updated_at)
          VALUES (:order,:file,'owned.pdf','A4','GRAYSCALE',1,false,1,1,now(),now()) RETURNING id
        """), {"order": ids["orders"][0], "file": ids["files"]["staged"]}).scalar_one()
        assert inserted
    with pytest.raises(DBAPIError):
        with actor_transaction(app, ids["users"]["one"]) as connection:
            connection.execute(text("""
              INSERT INTO order_items (order_id,uploaded_file_id,original_filename,paper_size,color_mode,
                quantity,is_rush,unit_price,line_total,created_at,updated_at)
              VALUES (:order,:file,'forged.pdf','A4','GRAYSCALE',1,false,1,1,now(),now())
            """), {"order": ids["orders"][0], "file": ids["files"]["private"]})
    with actor_transaction(app, ids["users"]["one"]) as connection:
        connection.execute(text("DELETE FROM orders"))
        assert connection.execute(text("SELECT id FROM orders")).scalars().all() == [ids["orders"][0]]


def test_postgres_verified_login_context_and_idor_routes(postgres_app):
    app, ids = postgres_app
    client = app.test_client()
    sign_in(client, ids["users"]["one"])
    assert client.get("/orders/POD-POLICY-1").status_code == 200
    assert client.get("/orders/POD-POLICY-2").status_code == 404
    assert client.get(f'/files/{ids["files"]["private"]}/download').status_code == 404
    sign_in(client, ids["users"]["blue"])
    assert client.get("/staff/orders/POD-POLICY-1").status_code == 200
    assert client.get("/staff/orders/POD-POLICY-2").status_code == 404


def test_postgres_authorized_professor_erasure_preserves_other_customers(postgres_app):
    app, ids = postgres_app
    client = app.test_client()
    sign_in(client, ids["users"]["blue"])
    csrf = token(client.get("/admin/professors"))
    response = client.post(f'/admin/professors/accounts/{ids["users"]["professor"]}/delete',
                           data={"csrf_token": csrf, "confirm_delete": "yes"})
    assert response.status_code == 302, response.get_data(as_text=True)
    with actor_transaction(app, ids["users"]["admin"]) as connection:
        assert connection.execute(text("SELECT id FROM orders ORDER BY id")).scalars().all() == [ids["orders"][i] for i in (0, 1, 3)]
        assert connection.execute(text("SELECT professor_id FROM orders WHERE id=:id"), {"id": ids["orders"][3]}).scalar_one() is None
        assert connection.execute(text("SELECT reviewed_by_id FROM payments WHERE id=:id"), {"id": ids["payments"][1]}).scalar_one() is None
        assert connection.execute(text("SELECT id FROM users WHERE id=:id"), {"id": ids["users"]["professor"]}).first() is None


def test_postgres_self_deletion_and_browser_cleanup(postgres_app):
    app, ids = postgres_app
    client = app.test_client()
    sign_in(client, ids["users"]["one"])
    csrf = token(client.get("/account/delete"))
    response = client.post("/account/delete", data={"csrf_token": csrf,
        "password": "A-strong-password-123", "confirm": "y"})
    assert response.status_code == 302
    assert response.headers["Clear-Site-Data"] == '"cache", "cookies", "storage"'
    with actor_transaction(app, ids["users"]["admin"]) as connection:
        assert connection.execute(text("SELECT id FROM users WHERE id=:id"),
            {"id": ids["users"]["one"]}).first() is None
        assert connection.execute(text("SELECT id FROM orders ORDER BY id")).scalars().all() == [ids["orders"][i] for i in (1, 2, 3)]


def test_postgres_deployment_checks_and_reversible_migration(postgres_app):
    app, ids = postgres_app
    result = app.test_cli_runner().invoke(args=["security-check"])
    assert "PASS Private tables enforce row-level security" in result.output
    assert "PASS Private row policies are installed without unexpected policies" in result.output
    assert "PASS Runtime DB account is separate from schema owner" in result.output
    assert "PASS Runtime DB account cannot assume an administrative role" in result.output
    db.session.remove()
    with db.engine.begin() as connection:
        connection.exec_driver_sql("RESET ROLE")
        with Operations.context(MigrationContext.configure(connection)):
            policy_migration().downgrade()
            assert connection.execute(text("SELECT count(*) FROM orders")).scalar_one() == 4
            policy_migration().upgrade()
        assert connection.execute(text("SELECT count(*) FROM pg_policies WHERE schemaname='public'")).scalar_one() == 19

