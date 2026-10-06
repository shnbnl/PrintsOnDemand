"""Unavailable rates and percentage rush are enforced by server quotations."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import PrintPrice, ServiceType, ShopService, PrintingShop
from app.routes.shops import detail_context
from test_checkout_flow import setup, post, print_fields
from test_orders import token


def test_zero_rate_is_unselectable_and_server_rejects_forged_choice(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    with test_app.app_context():
        price = db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == shop_id))
        price.price = Decimal('0.00')
        db.session.commit()
        assert not detail_context(db.session.get(PrintingShop, shop_id))['price_map']
    fields = {'shop_id': shop_id, **print_fields(file_id)}
    response = post(client, '/checkout/shop', fields)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert 'value="A4:GRAYSCALE"' not in html
    assert 'not offered' in html and '—' in html
    response = client.post('/checkout/shop', headers={'Accept': 'application/json'}, data={
        **fields, 'intent': 'quote', 'csrf_token': token(client.get('/checkout/upload')),
        f'print_choice_{file_id}': 'A4:GRAYSCALE',
    })
    assert response.status_code == 400
    with test_app.app_context():
        price = db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == shop_id))
        price.price = Decimal('2.25')
        db.session.commit()
    db.session.expire_all()
    response = post(client, '/checkout/shop', fields)
    assert response.status_code == 302, response.get_data(as_text=True)


@pytest.mark.parametrize(('price', 'quantity', 'expected'), [('2.25', '4', '1.80'), ('0.03', '1', '0.01')])
def test_rush_works_without_legacy_fee_and_rounds_currency(client, test_app, price, quantity, expected):
    owner, shop_id, file_id = setup(client, test_app)
    with test_app.app_context():
        rate = db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == shop_id))
        rate.price = Decimal(price)
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.RUSH_PRINTING, enabled=True))
        db.session.commit()
    fields = {'shop_id': shop_id, **print_fields(file_id, quantity=quantity), f'is_rush_{file_id}': '1'}
    response = client.post('/checkout/shop', headers={'Accept': 'application/json'}, data={
        **fields, 'intent': 'quote', 'csrf_token': token(client.get('/checkout/upload')),
    })
    assert response.status_code == 200
    assert Decimal(response.json['rush_fee']) == Decimal(expected)
    assert Decimal(response.json['total']) == Decimal(price) * int(quantity) + Decimal(expected)
