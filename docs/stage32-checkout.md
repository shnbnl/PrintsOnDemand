# Stage 32: combined Shop workspace

The customer checkout sequence is **Upload → Shop → Fulfillment → Payment → Review → Success**.

## Behavior

- Shop now combines the existing map with one selected-shop panel: photo (or the existing initial fallback), name, hours, address, services, prices, fees, per-file paper size/output/count/rush settings, printing total, and Proceed.
- Desktop uses a large map beside the panel; mobile stacks the map, shop information, rates, settings, total, and Proceed. Desktop hover previews show only the shop name and hours. Selecting a pin updates the single panel without navigating away.
- The old shop-list section and persistent map overlays are removed. A compact selector uses the same workspace when Maps is unavailable or active shops lack coordinates. Native form submission also supports Shop selection and Proceed without JavaScript.
- Price previews call the existing server pricing service; they do not persist configurations or create orders. Proceed validates the settings and saves configurations only for the customer's unexpired, unattached staged files. Frontend prices are never authoritative.
- Shop changes retain files and print choices, clear unsupported rush, revalidate available rates, and clear downstream fulfillment/payment/review state. Unsupported paper/output combinations show an error instead of proceeding.
- Fulfillment contains receiving-method choices only. It has neither print controls nor a Selected Shop section. Old GET `/checkout/configure` bookmarks redirect to `/checkout/fulfillment`; the old combined POST form is retired.
- Existing receiving-method validation, delivery fees, Blue and Silver professor/faculty eligibility, managed Faculty snapshots, online reference requirements, manual payment verification, order creation, and authorization services remain in use.
- Shop ratings do not exist in the current data model. The panel displays **Rating not available**, rather than inventing a rating.

## Files changed

| File | Change |
| --- | --- |
| `app/routes/checkout.py` | Shop selection/quotation/print-setting submission; fulfillment-only route; compatible old bookmark; updated navigation. |
| `app/services/pricing.py` | Allow an explicit, validated set of print options to be quoted before a staged file has a persisted configuration. |
| `app/static/css/app.css` | Responsive workspace layout; remove obsolete checkout map-overlay styles. |
| `app/static/js/shop-map.js` | Pin selection updates the workspace; concise hover previews; compact fallback; clear highlight for a shop without coordinates. |
| `app/static/js/checkout-shop.js` | New queued selection requests and server price previews; prevent stale responses or editing during panel replacement. |
| `app/static/js/checkout-print-settings.js` | Delegated count controls work after panel replacement. Replaces deleted `checkout-configure.js`. |
| `app/templates/checkout/shop.html` | Single map/workspace layout and fallback selector. |
| `app/templates/checkout/shop_workspace.html` | New selected-shop, price-table, settings, total, and Proceed partial. |
| `app/templates/checkout/print_settings.html` | Per-file controls moved into Shop. |
| `app/templates/checkout/fulfillment.html` | Fulfillment-only page; replaces deleted `configure.html`. |
| `app/templates/checkout/progress.html` | Fulfillment label and endpoint. |
| `app/templates/checkout/payment.html` | Back to Fulfillment. |
| `app/templates/checkout/review.html` | Separate links to edit print settings and fulfillment. |
| `tests/test_checkout_flow.py` | Helpers and order/payment regression tests follow the new step boundaries. |
| `tests/test_checkout_delivery_shops.py` | Shop-specific delivery regression tests use Fulfillment. |
| `tests/test_shop_checkout_fixes.py` | Single-workspace form assertions and fulfillment navigation. |
| `tests/test_stage30_checkout_storage.py` | Staging, map, and paper/output/count/rush checks use Shop. |
| `tests/test_stage31_fulfillment.py` | Existing professor/faculty restrictions tested through the new route. |
| `tests/test_stage32_workspace.py` | Read-only previews, state preservation/repricing, duplicate/foreign input rejection, step separation, and immutable print settings at Fulfillment. |
| `README.md` | Current flow, workspace/fallback behavior, and rating limitation. |
| `docs/stage32-checkout.md` | This implementation and verification report. |

No model, migration, dependency, API key, map ID, coordinate storage, or payment-verification changes were required. Browser fixtures used isolated temporary databases and upload directories.

## Verification

- Full `pytest -q`: **446 passed**, with one existing Flask-Login `datetime.utcnow()` deprecation warning.
- After the last mobile table-label change: **17 checkout/workspace tests passed**.
- `python -m pip check`: **No broken requirements found**.
- `flask --app run.py db check`: **No new upgrade operations detected**.
- `git diff --check`: passed.
- Headless Chrome: Student and Professor, each at **1440, 1280, 430, and 390 px**, selecting all four shops; pin emphasis, hover/tap, one panel, file preservation, paper/output/count/rush, server-matched displayed totals, delivery, pickup, onsite/online payments, Review, Back navigation, and successful order creation passed.
- Separate Student-to-professor and Professor-to-faculty Blue and Silver orders passed, including managed Faculty and online-only payment.
- No horizontal page overflow, clipped Proceed controls, broken images, or JavaScript errors in the successful deterministic walkthrough. Final mobile price labels and count buttons were rechecked at 390 and 430 px.
- Map-load failure, Shop selection/Proceed with JavaScript disabled, inactive-shop exclusion, and access to an active shop without coordinates passed.

**External verification limit:** live Google Maps could not load in this environment. Map interactions were tested with a deterministic Maps API substitute using the supplied marker coordinates, and actual provider-load failure was tested separately. This does not verify the live provider's basemap or deployment key/referrer configuration.

The existing price model still charges per print count, without document page counting, page ranges, or duplex settings. Payment remains manual and requires existing staff verification.

Changes were left uncommitted and unpushed on `main` for review.
