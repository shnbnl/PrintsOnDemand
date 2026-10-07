"""Stage 15 checkout, item snapshots, limits, and existing access controls."""

from decimal import Decimal
from html import unescape
import re

from sqlalchemy import select

from app.extensions import db
from app.models import (
    ColorMode, Order, OrderItem, PaperSize, PaymentMethod, PrintConfiguration,
    PrintPrice, PrintingShop, UploadedFile, User, UserRole,
)
from test_orders import (
    PDF, approved_professor, file, offer_professor_service, place, review,
    pickup_fields, shop, sign_in, student, token,
)


def extra_rate(app, shop_id, size=PaperSize.A3, mode=ColorMode.COLOR, price="7.25"):
    with app.app_context():
        db.session.add(PrintPrice(
            shop_id=shop_id, paper_size=size, color_mode=mode, price=Decimal(price),
        ))
        db.session.commit()


def selection(first, second, shop_id, *, rush=True):
    result = {
        "file_id": [str(first), str(second)], "shop_id": str(shop_id),
        **pickup_fields(),
        f"paper_size_{first}": "A4", f"color_mode_{first}": "GRAYSCALE",
        f"quantity_{first}": "2",
        f"paper_size_{second}": "A3", f"color_mode_{second}": "COLOR",
        f"quantity_{second}": "3",
    }
    if rush:
        result[f"is_rush_{first}"] = "1"
    return result


def multi_review(client, fields):
    return client.get("/orders/new", query_string=fields)


def multi_place(client, fields, **extras):
    if fields.get("destination") == "PROFESSOR":
        fields = {key: value for key, value in fields.items() if key not in {"pickup_date", "pickup_slot"}}
    return client.post("/orders/create", data={
        **fields, "csrf_token": token(client.get("/student")), **extras,
    })


def prepared(client, app, *, rush=True):
    owner = student(app)
    shop_id = shop(app, rush=rush)
    first = file(app, owner, name="Thesis.pdf")
    second = file(app, owner, name="Poster.pdf")
    extra_rate(app, shop_id)
    sign_in(client, owner)
    return owner, shop_id, first, second


def test_two_files_have_independent_settings_prices_and_atomic_snapshots(client, test_app):
    owner, shop_id, first, second = prepared(client, test_app)
    fields = selection(first, second, shop_id)
    reviewed = multi_review(client, fields)
    assert reviewed.status_code == 200
    for expected in (b"Thesis.pdf", b"Poster.pdf", b"PHP 4.50", b"PHP 21.75",
                     b"Subtotal: PHP 26.25", b"Rush printing fee: PHP 20.00",
                     b"Total: PHP 46.25"):
        assert expected in reviewed.data
    response = multi_place(
        client, fields, unit_price="0.01", line_total="0.01", subtotal="0.01",
        fees_total="0.01", total="0.01",
    )
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert b"Print details (2 files)" in detail.data
    assert b"Thesis.pdf" in detail.data and b"Poster.pdf" in detail.data
    assert b"PHP 46.25" in detail.data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.user_id == owner and order.shop_id == shop_id
        assert len(order.items) == 2
        assert [item.uploaded_file_id for item in order.items] == [first, second]
        assert [(item.paper_size, item.color_mode, item.quantity) for item in order.items] == [
            (PaperSize.A4, ColorMode.GRAYSCALE, 2),
            (PaperSize.A3, ColorMode.COLOR, 3),
        ]
        assert [item.unit_price for item in order.items] == [Decimal("2.25"), Decimal("7.25")]
        assert [item.line_total for item in order.items] == [Decimal("4.50"), Decimal("21.75")]
        assert (order.subtotal, order.rush_fee, order.fees_total, order.total) == (
            Decimal("26.25"), Decimal("20.00"), Decimal("20.00"), Decimal("46.25"),
        )
        assert all(type(item.line_total) is Decimal for item in order.items)
        # Checkout overrides do not change the student's reusable library defaults.
        assert db.session.get(PrintConfiguration, db.session.get(UploadedFile, second).configuration.id).paper_size == PaperSize.A4


def test_two_rush_files_pay_one_order_level_rush_fee(client, test_app):
    _, shop_id, first, second = prepared(client, test_app)
    fields = selection(first, second, shop_id)
    fields[f"is_rush_{second}"] = "1"
    reviewed = multi_review(client, fields)
    assert reviewed.status_code == 200
    assert b"Total: PHP 46.25" in reviewed.data
    assert multi_place(client, fields).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert all(item.is_rush for item in order.items)
        assert order.rush_fee == order.fees_total == Decimal("20.00")


def test_tampered_item_settings_are_rejected_server_side(client, test_app):
    _, shop_id, first, second = prepared(client, test_app)
    for key, value in (
        (f"paper_size_{second}", "OTHER"),
        (f"color_mode_{second}", "NEON"),
        (f"quantity_{second}", "999999999999999999999999999"),
        (f"is_rush_{second}", "yes"),
    ):
        fields = selection(first, second, shop_id)
        fields[key] = value
        assert multi_review(client, fields).status_code == 400
        assert multi_place(client, fields).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_removing_and_readding_file_only_changes_draft(client, test_app):
    owner, shop_id, first, second = prepared(client, test_app, rush=False)
    selection_page = client.get("/orders/new", query_string={"file_id": first, "shop_id": shop_id, "edit": "1"})
    assert selection_page.status_code == 200
    assert b"+ Add files" in selection_page.data
    assert b"Remove from order" in selection_page.data
    both = selection(first, second, shop_id, rush=False)
    reviewed = multi_review(client, both)
    assert reviewed.status_code == 200
    remove_url = unescape(re.search(
        r'href="([^"]+)"[^>]*>Remove from order</a>',
        reviewed.get_data(as_text=True),
    ).group(1))
    draft = client.get(remove_url)
    assert draft.status_code == 200
    assert b"Poster.pdf" in draft.data and b"Thesis.pdf" in draft.data
    removed = {"file_id": [str(first)], "shop_id": str(shop_id), **pickup_fields()}
    assert multi_review(client, removed).status_code == 200
    with test_app.app_context():
        assert db.session.get(UploadedFile, second).user_id == owner
        assert db.session.scalar(select(Order)) is None
    assert multi_review(client, both).status_code == 200
    assert multi_place(client, both).status_code == 302
    with test_app.app_context():
        assert len(db.session.scalar(select(Order)).items) == 2


def test_zero_duplicates_and_limit_are_rejected(client, test_app):
    _, shop_id, first, second = prepared(client, test_app)
    assert b"Select at least one file" in client.get(
        "/orders/new", query_string={"review": "1", "shop_id": shop_id}
    ).data
    zero = multi_place(client, {"shop_id": str(shop_id)})
    assert zero.status_code == 400 and b"Select at least one file" in zero.data
    duplicate = {"file_id": [str(first), str(first)], "shop_id": str(shop_id)}
    assert b"only once" in multi_review(client, duplicate).data
    assert multi_place(client, duplicate).status_code == 400
    test_app.config["ORDER_MAX_FILES"] = 1
    assert b"no more than 1 files" in multi_review(client, selection(first, second, shop_id)).data
    assert multi_place(client, selection(first, second, shop_id)).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
        assert db.session.scalar(select(OrderItem)) is None


def test_foreign_or_invalid_second_file_creates_no_partial_order(client, test_app):
    owner, shop_id, first, second = prepared(client, test_app)
    outsider = student(test_app, "outsider@example.edu")
    foreign = file(test_app, outsider, name="private.pdf")
    forbidden = {"file_id": [str(first), str(foreign)], "shop_id": str(shop_id)}
    assert multi_review(client, forbidden).status_code == 404
    assert multi_place(client, forbidden).status_code == 404
    missing_price = selection(first, second, shop_id)
    missing_price[f"paper_size_{second}"] = "A2"
    assert multi_review(client, missing_price).status_code == 400
    assert multi_place(client, missing_price).status_code == 400
    malformed = selection(first, second, shop_id)
    malformed[f"quantity_{second}"] = "0"
    assert multi_review(client, malformed).status_code == 400
    assert multi_place(client, malformed).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
        assert db.session.scalar(select(OrderItem)) is None
        assert db.session.get(UploadedFile, first).user_id == owner


def test_change_to_one_item_requires_fresh_review_and_retry_is_not_duplicate(client, test_app):
    _, shop_id, first, second = prepared(client, test_app)
    fields = selection(first, second, shop_id)
    assert multi_review(client, fields).status_code == 200
    changed = {**fields, f"quantity_{second}": "4"}
    assert multi_place(client, changed).status_code == 409
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
    assert multi_place(client, changed).status_code == 302
    assert multi_place(client, changed).status_code == 409
    with test_app.app_context():
        assert db.session.query(Order).count() == 1
        assert db.session.query(OrderItem).count() == 2


def test_old_single_file_order_and_multi_order_history_keep_snapshots(client, test_app):
    _, shop_id, first, second = prepared(client, test_app, rush=False)
    assert review(client, first, shop_id).status_code == 200
    old_url = place(client, first, shop_id).headers["Location"]
    fields = selection(first, second, shop_id, rush=False)
    assert multi_review(client, fields).status_code == 200
    new_url = multi_place(client, fields).headers["Location"]
    with test_app.app_context():
        old = db.session.scalar(select(Order).where(Order.order_reference == old_url.rsplit("/", 1)[1]))
        old_total = old.total
        db.session.get(PrintingShop, shop_id).prices[0].price = Decimal("9.00")
        db.session.commit()
    old_detail = client.get(old_url)
    assert old_detail.status_code == 200
    assert b"Print details (1 file)" in old_detail.data
    assert f"PHP {old_total}".encode() in old_detail.data
    assert b"Poster.pdf" not in old_detail.data
    new_detail = client.get(new_url)
    assert b"Print details (2 files)" in new_detail.data
    assert b"PHP 26.25" in new_detail.data
    history = client.get("/orders")
    assert history.status_code == 200
    assert old_url.rsplit("/", 1)[1].encode() in history.data
    assert new_url.rsplit("/", 1)[1].encode() in history.data


def test_multi_order_professor_payment_and_staff_file_isolation(client, test_app):
    from test_payments import configured_online
    configured_online(test_app)
    owner, shop_id, first, second = prepared(client, test_app)
    other_shop = shop(test_app, name="Other Shop")
    staff = student(test_app, "staff@example.edu", UserRole.SHOP_STAFF)
    other_staff = student(test_app, "other-staff@example.edu", UserRole.SHOP_STAFF)
    with test_app.app_context():
        db.session.get(User, staff).shop_id = shop_id
        db.session.get(User, other_staff).shop_id = other_shop
        db.session.commit()
    offer_professor_service(test_app, shop_id)
    professor = approved_professor(test_app)
    fields = {key: value for key, value in selection(first, second, shop_id).items()
              if key not in {"pickup_date", "pickup_slot"}}
    fields.update(destination="PROFESSOR", professor_id=str(professor))
    reviewed = multi_review(client, fields)
    assert reviewed.status_code == 200 and b"Maria Santos" in reviewed.data
    assert client.post("/orders/create", data=fields).status_code == 400  # CSRF
    order_url = multi_place(client, fields).headers["Location"]
    assert client.get(order_url).status_code == 200
    assert b"Maria Santos" in client.get(order_url).data
    method = client.post(order_url + "/payment", data={
        "csrf_token": token(client.get(order_url)), "payment_method": "ONLINE",
    })
    assert method.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.professor_id == professor
        assert order.payment.payment_method == PaymentMethod.ONLINE
        assert order.payment.amount == order.total
        item_ids = [item.id for item in order.items]
    staff_url = order_url.replace("/orders/", "/staff/orders/", 1)
    sign_in(client, staff)
    detail = client.get(staff_url)
    assert b"Thesis.pdf" in detail.data and b"Poster.pdf" in detail.data
    for item_id in item_ids:
        downloaded = client.get(f"{staff_url}/files/{item_id}/download")
        assert downloaded.status_code == 200 and downloaded.data == PDF
    sign_in(client, other_staff)
    assert client.get(staff_url).status_code == 404
    for item_id in item_ids:
        assert client.get(f"{staff_url}/files/{item_id}/download").status_code == 404
    sign_in(client, owner)
    assert client.get(f"{staff_url}/files/{item_ids[0]}/download").status_code == 403
