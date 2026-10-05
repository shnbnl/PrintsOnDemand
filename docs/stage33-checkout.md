# Stage 33: embedded map workspace and selectable prices

The Shop step now uses a large map with one embedded workspace panel. Desktop places the panel inside the right edge of the map; mobile uses a bottom sheet inside the map. The panel scrolls internally, keeps Total and Proceed visible, and can be minimized to reach map pins. Shop information is limited to name/photo, hours, and enabled services.

The price table is the paper/output selector. Each available price cell is a labeled native radio control with keyboard navigation, visible focus, and a selected checkmark. There are no separate paper-size or color selectors, price/fee section, rating placeholder, or long shop descriptions. Missing rates are shown as **Not offered** and cannot be selected.

## Stored prices and state

`PrintPrice` stores one `Numeric(10, 2)` price per shop/paper-size/color-mode combination, with a uniqueness constraint. It has no range fields. The table therefore displays those single prices, formatted to two decimals, without copying reference-image prices or inventing ranges.

The compact file selector changes which file's controls are visible. Each file retains its own paper/output combination, count, and rush choice, including when shops change. The existing checkout service recalculates totals from all files and validates rates and services. The backend adapter translates the combined radio value into the existing paper/color options; it never accepts a browser price as authoritative. Existing explicit paper/color submissions remain supported for earlier checkout forms.

The pricing engine, data models, payment verification, fulfillment services, professor eligibility rules, file authorization, and order snapshots are unchanged. The existing count-based price calculation remains in place; the UI explains that document pages are not counted automatically.

## Changed files

- `app/routes/checkout.py`: validate combined price-cell input and pass its paper/output pair to existing validation.
- `app/templates/checkout/shop.html`: embed the single workspace panel in the map container, with minimize/open control.
- `app/templates/checkout/shop_workspace.html`: concise shop information and internally scrolling content with a persistent total/Proceed footer.
- `app/templates/checkout/print_settings.html`: compact file selector, database-backed selectable price table, independent counts and rush settings.
- `app/static/js/checkout-shop.js`: active-file switching, combined price selection, panel control, invalid-field reveal, existing server quote updates.
- `app/static/js/shop-map.js`: place map controls away from the panel and offset the initial viewport to expose pins; marker coordinates remain unchanged.
- `app/static/css/app.css`: embedded desktop panel, mobile sheet, compact table, selected/focus states, internal scrolling.
- `tests/test_stage30_checkout_storage.py`: update the paper-option markup assertion for combined radio values.
- `tests/test_stage33_price_cells.py`: ten new test cases covering both roles/all shops, every stored rate, unavailable/forged/duplicate choices, and independent two-file settings/totals.
- `README.md`: current workspace interaction and price-storage behavior.
- `docs/stage33-checkout.md`: this report.

No files were removed. No dependencies or migrations were added. No shop records, stored prices, or historical orders were changed.

## Verification

- Full suite: **456 passed**, with the existing Flask-Login `datetime.utcnow()` deprecation warning.
- Focused Stage 32/33 tests after final presentation changes: **15 passed**.
- `pip check`: no broken requirements.
- `git diff --check`: passed.

Headless Chrome walkthroughs passed for Student and Professor at **1440, 1280, 430, and 390 px**. Each run exercised all four shops and all ten paper/color cells, keyboard selection, two independent files, count/rush settings, server-matched totals, embedded-panel bounds, no horizontal page overflow, delivery, payment, Review, and order creation. Separate Blue and Silver professor/faculty workflows passed with managed Faculty and online-only payment. The provider-failure selector updated the same embedded workspace and proceeded successfully. No JavaScript errors or broken images were reported in the successful deterministic walkthrough.

The final two-file test also verified the persisted order snapshots and total for different paper/output/count choices with normal printing on one file and rush on the other; all ten focused Stage 33 tests passed after that additional assertion.

Browser fixtures used isolated temporary databases and private upload directories. **Live Google Maps was unavailable in this environment.** Pin interactions used the existing deterministic API substitute, with the real provider-load failure checked separately. The live basemap and deployment key/referrer configuration could not be verified here.

No commit or push was performed.
