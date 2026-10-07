"""The embedded pricing table selects actual per-file configurations."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from werkzeug.datastructures import MultiDict

from app.extensions import db
from app.models import ColorMode, FeeType, Order, PaperSize, PrintPrice, ServiceType, ShopFee, ShopService, UserRole
from test_checkout_delivery_shops import SHOPS, seeded_shop
from test_checkout_flow import post, print_fields, setup, upload_checkout_file
from test_orders import pickup_fields, sign_in, student, token


@pytest.mark.parametrize('name', SHOPS)
@pytest.mark.parametrize('role', [UserRole.STUDENT, UserRole.PROFESSOR])
def test_every_price_cell_matches_stored_rate_and_configuration(client, test_app, name, role):
    shop_id = seeded_shop(test_app, name)
    owner = student(test_app, role=role)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    assert post(client, '/checkout/shop', {'shop_id': shop_id, **print_fields(file_id)}).status_code == 302
    page = client.get('/checkout/shop').get_data(as_text=True)
    assert page.index('class="workspace-panel"') < page.index('data-pin-preview')
    assert 'Print prices &amp; fees' not in page and 'Rating not available' not in page
    assert 'Sample shop based on' not in page.split('<script id="map-shop-data"')[0]
    assert 'type="radio" name="paper_size_' not in page
    assert 'type="radio" name="color_mode_' not in page
    with test_app.app_context():
        rates = [(rate.paper_size.value, rate.color_mode.value, rate.price) for rate in
                 db.session.scalars(select(PrintPrice).where(PrintPrice.shop_id == shop_id))]
    assert len(rates) == 10
    for size, mode, price in rates:
        assert f'value="{size}:{mode}"' in page
        assert f'PHP {price}' in page
        quote = client.post('/checkout/shop', headers={'Accept': 'application/json'}, data={
            'csrf_token': token(client.get('/checkout/upload')), 'shop_id': shop_id, 'intent': 'quote',
            **print_fields(file_id, quantity='2'), f'print_choice_{file_id}': f'{size}:{mode}',
            'price': '0.01', 'total': '0.01',
        })
        assert quote.status_code == 200
        assert Decimal(quote.json['total']) == price * 2


def test_missing_rates_are_not_selectable_and_compound_values_are_validated(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    assert post(client, '/checkout/shop', {'shop_id': shop_id, **print_fields(file_id)}).status_code == 302
    page = client.get('/checkout/shop').get_data(as_text=True)
    assert 'value="A4:GRAYSCALE"' in page
    assert 'value="A4:COLOR"' not in page and 'not offered' in page
    for invalid in ['A4:COLOR', 'A4:NEON', 'A9:COLOR', 'A4', 'A4:COLOR:0.01']:
        assert post(client, '/checkout/shop', {'shop_id': shop_id, **print_fields(file_id),
                    f'print_choice_{file_id}': invalid}).status_code == 400
    fields = MultiDict({'csrf_token': token(client.get('/checkout/upload')), 'shop_id': shop_id, **print_fields(file_id)})
    fields.setlist(f'print_choice_{file_id}', ['A4:GRAYSCALE', 'A4:COLOR'])
    assert client.post('/checkout/shop', data=fields).status_code == 400


def test_two_files_keep_independent_combined_choices_and_counts(client, test_app):
    owner, shop_id, first = setup(client, test_app)
    second = upload_checkout_file(client, test_app, owner, 'portfolio.pdf')
    with test_app.app_context():
        db.session.add(PrintPrice(shop_id=shop_id, paper_size=PaperSize.LETTER,
                                  color_mode=ColorMode.COLOR, price=Decimal('7.25')))
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.RUSH_PRINTING, enabled=True))
        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.RUSH_PRINTING, amount=Decimal('5.00')))
        db.session.commit()
    response = post(client, '/checkout/shop', {'shop_id': shop_id,
        **print_fields(first, quantity='2'), **print_fields(second, quantity='3'),
        'file_id': [str(first), str(second)], f'print_choice_{first}': 'LETTER:COLOR',
        f'print_choice_{second}': 'A4:GRAYSCALE', f'is_rush_{second}': '1'})
    assert response.status_code == 302
    with client.session_transaction() as state:
        choices = state['checkout_draft']['options']
        assert choices[str(first)] == dict(paper_size='LETTER', color_mode='COLOR', quantity=2, is_rush=False)
        assert choices[str(second)] == dict(paper_size='A4', color_mode='GRAYSCALE', quantity=3, is_rush=True)
    page = client.get('/checkout/shop').get_data(as_text=True)
    assert 'PHP 41.25' in page
    assert page.count('data-file-settings=') == 2
    assert post(client, '/checkout/fulfillment', pickup_fields()).status_code == 302
    assert post(client, '/checkout/payment', {'payment_method': 'ONSITE'}).status_code == 302
    assert post(client, '/checkout/place').status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.total == Decimal('41.25')
        items = {item.uploaded_file_id: item for item in order.items}
        assert (items[first].paper_size, items[first].color_mode, items[first].quantity, items[first].is_rush) == (PaperSize.LETTER, ColorMode.COLOR, 2, False)
        assert (items[second].paper_size, items[second].color_mode, items[second].quantity, items[second].is_rush) == (PaperSize.A4, ColorMode.GRAYSCALE, 3, True)
