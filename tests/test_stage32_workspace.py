"""Combined Shop workspace state, quotation, and fulfillment boundary regressions."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.models import ColorMode, FeeType, Order, PaperSize, PrintConfiguration, PrintPrice, ServiceType, ShopFee, ShopService
from test_checkout_flow import post, print_fields, setup, upload_checkout_file
from test_orders import pickup_fields, shop, token


def workspace_post(client, shop_id, uploaded_id, intent="select", **overrides):
    return client.post("/checkout/shop", headers={"Accept": "application/json"}, data={
        "csrf_token": token(client.get("/checkout/upload")), "shop_id": str(shop_id),
        "intent": intent, **print_fields(uploaded_id), **overrides,
    })


@pytest.mark.parametrize("professor", [False, True])
def test_selection_stays_in_workspace_and_quote_is_read_only(client, test_app, professor):
    _, shop_id, file_id = setup(client, test_app, professor=professor)
    response = workspace_post(client, shop_id, file_id)
    assert response.status_code == 200
    assert response.json["shop_id"] == shop_id
    assert response.json["html"].count('data-current-shop=') == 1
    assert "Print settings" in response.json["html"]
    with client.session_transaction() as state:
        before = state["checkout_draft"].copy()
    quote = workspace_post(client, shop_id, file_id, "quote", **{f"quantity_{file_id}": "3", "total": "0.01"})
    assert quote.status_code == 200 and quote.json["total"] == "6.75"
    with client.session_transaction() as state:
        assert state["checkout_draft"] == before
    with test_app.app_context():
        assert db.session.scalar(select(PrintConfiguration)) is None
        assert db.session.scalar(select(Order)) is None
    response = post(client, "/checkout/shop", {"shop_id": str(shop_id), **print_fields(file_id, quantity="3")})
    assert response.headers["Location"].endswith("/checkout/fulfillment")
    page = client.get(response.headers["Location"])
    assert b"Fulfillment" in page.data
    assert b"Selected shop" not in page.data and b"Print settings" not in page.data
    assert b'name="paper_size_' not in page.data and b'name="shop_id"' not in page.data
    assert client.get("/checkout/configure").headers["Location"].endswith("/checkout/fulfillment")
    assert client.post("/checkout/configure", data={}).status_code in (400, 405)


def test_switch_reprices_keeps_files_and_valid_options_clears_downstream(client, test_app):
    owner, first, file_id = setup(client, test_app)
    other_file = upload_checkout_file(client, test_app, owner, "second.pdf")
    second = shop(test_app, name="Second shop")
    with test_app.app_context():
        db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == second)).price = Decimal("8.00")
        db.session.add(ShopService(shop_id=first, service_type=ServiceType.RUSH_PRINTING, enabled=True))
        db.session.add(ShopFee(shop_id=first, fee_type=FeeType.RUSH_PRINTING, amount=Decimal("5.00")))
        db.session.commit()
    fields = {**print_fields(file_id, quantity="3"), **print_fields(other_file, quantity="2"),
              "file_id": [str(file_id), str(other_file)], f"is_rush_{file_id}": "1"}
    assert post(client, "/checkout/shop", {"shop_id": str(first), **fields}).status_code == 302
    assert post(client, "/checkout/fulfillment", pickup_fields()).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    response = workspace_post(client, second, file_id, **fields)
    assert response.status_code == 200 and "PHP 40.00" in response.json["html"]
    with client.session_transaction() as state:
        saved = state["checkout_draft"]
        assert saved["file_ids"] == [file_id, other_file]
        assert saved["options"][str(file_id)]["quantity"] == 3
        assert saved["options"][str(other_file)]["quantity"] == 2
        assert saved["options"][str(file_id)]["is_rush"] is False
        assert not any(key in saved for key in ("fulfillment", "payment_method", "review"))
    forged = workspace_post(client, second, file_id, "quote", **fields)
    assert forged.status_code == 400  # Unsupported rush cannot be forced into a quote.


def test_switch_replaces_unavailable_configuration_with_explicit_notice(client, test_app):
    _, first, file_id = setup(client, test_app)
    second = shop(test_app, name="Limited shop")
    with test_app.app_context():
        db.session.add(PrintPrice(shop_id=first, paper_size=PaperSize.A3,
                                  color_mode=ColorMode.COLOR, price=Decimal("20.00")))
        db.session.commit()
    options = {**print_fields(file_id, quantity="2"),
               f"paper_size_{file_id}": "A3", f"color_mode_{file_id}": "COLOR"}
    selected = workspace_post(client, first, file_id, **options)
    assert selected.status_code == 200
    switched = workspace_post(client, second, file_id, **options)
    assert switched.status_code == 200
    assert "A3 Color is not offered" in switched.json["notice"]
    assert "selected A4 Grayscale instead" in switched.json["notice"]
    with client.session_transaction() as state:
        saved = state["checkout_draft"]
        assert saved["file_ids"] == [file_id]
        assert saved["options"][str(file_id)]["paper_size"] == "A4"
        assert saved["options"][str(file_id)]["color_mode"] == "GRAYSCALE"
        assert saved["options"][str(file_id)]["quantity"] == 2


def test_workspace_rejects_incomplete_duplicate_and_foreign_file_settings(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    csrf = token(client.get("/checkout/upload"))
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id)}).status_code == 400
    assert workspace_post(client, shop_id, file_id, file_id="999999").status_code == 400
    data = MultiDict({"csrf_token": csrf, "shop_id": str(shop_id), **print_fields(file_id)})
    data.add(f"quantity_{file_id}", "999")
    assert client.post("/checkout/shop", data=data).status_code == 400
    assert client.post("/checkout/shop", data={"shop_id": str(shop_id), **print_fields(file_id)}).status_code == 400
    assert client.get("/checkout/fulfillment").headers["Location"].endswith("/checkout/shop")


def test_fulfillment_cannot_override_print_settings(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id), **print_fields(file_id, quantity="3")}).status_code == 302
    assert post(client, "/checkout/fulfillment", {**pickup_fields(), f"quantity_{file_id}": "999", "shop_id": "999"}).status_code == 302
    assert b"PHP 6.75" in client.get("/checkout/payment").data
    with client.session_transaction() as state:
        assert state["checkout_draft"]["shop_id"] == shop_id
        assert state["checkout_draft"]["options"][str(file_id)]["quantity"] == 3
