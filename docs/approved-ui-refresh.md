# Approved campus printing desk design

This presentation update applies the approved desktop/mobile mockups to the existing Flask application. The original logo assets and navy, cobalt, cream, and status colors remain authoritative. Mockup names, rates, and order data are not copied into application data.

## Shared interface

- Consistent typography, spacing, rounded surfaces, quieter borders, and form controls across landing/authentication, student/professor, checkout, history/tracking, account, shop staff, and administration pages.
- A prominent Start Order card with vector icons for the existing printing desk destinations. Account details and professor verification remain visible.
- The existing role-based navigation, mobile menu, back links, five checkout steps, form labels, validation, and actions are preserved.
- Responsive tables/cards and 16px mobile form inputs avoid unnecessary horizontal scrolling and focus zoom. Keyboard focus indicators and reduced-motion support remain available.

## Big-map workspace

Both shop discovery and checkout retain their embedded information panel. Desktop uses a floating panel with independently scrolling details and an always-visible checkout total/action. On mobile the panel flows inside the map container below the visible map area; the page scrolls as a whole, and the existing minimize control exposes the map.

The mobile map canvas has a stable height as shop settings expand. Initial camera panning centers the shop locations above the panel, based on the visible canvas area. This is a viewport adjustment only: database coordinates, marker construction, hover/selection requests, Google Maps configuration, and checkout pricing are unchanged.

## Validation

The isolated browser audit covers guest, student, professor, all four shop staff accounts, and admin pages at 320, 390, 768, 1024, and 1440px. It also exercises file upload, shop selection, quantity/quote updates, panel minimization, fulfillment, onsite payment selection, order placement, history, and tracking. Browser data and uploads are isolated from the local application's database.

Google Maps is stubbed for repeatable browser checks; these checks validate layout and interactions rather than live map tiles or API availability. Chromium mobile viewport checks are not physical iPhone/Safari or Android device certification.

No schema, business-rule, authentication, payment, storage, or API dependency changes are included.

## Screenshot alignment refinement

`campus-concept.css`, loaded by the shared base template, applies the approved ivory/navy printing-desk treatment to every role's existing pages. The customer desk uses the approved headline and primary card copy. Existing destinations and account details remain accessible.

Both embedded map panels use the dark navy surfaces shown in the approved shop-workspace screenshots, including coordinated inputs, selectable price cells, file controls and totals. Minimizing preserves the selected shop heading while hiding configuration. The mobile sheet remains within the map container. Original brand assets, live map tiles and shop photos are retained; illustrative map geometry, invented order summaries and mock prices are not introduced.
