# Current-product UI redesign

The existing Flask routes, role checks, forms, order state, pricing, payment verification, file storage, professor eligibility, and map provider remain authoritative. This redesign changes presentation and progressive client feedback only.

## Current-state audit

- One Jinja base supplies navigation and flash messages for Student, Professor, Shop Staff, and Admin. Customer checkout is Upload → Shop → Fulfillment → Payment → Review → Success. The Shop step uses an embedded map panel with a clickable price table, multi-file settings, and pin previews. Staff and admin tools use separate management forms and operational lists.
- `app.css` contains reusable cards, buttons, fields, badges, tables, and responsive rules, alongside older screen-specific layers. Those layers produce uneven density, rounded controls, and different table/card treatments across roles. Native mobile navigation and checkout progress already exist and should be refined rather than replaced.
- The route and model inventory confirms shop-scoped staff access, Blue and Silver-only professor management, customer order ownership, and staff payment verification. Presentation changes must keep each server-rendered action, form field, CSRF token, and guarded link in its current role.

## Implementation direction

1. Use the current navy, cobalt, cream, and logo in a tighter token-based visual system: clearer type scale, disciplined spacing, restrained elevation, consistent buttons, forms, notices, badges, and tables.
2. Give landing and authentication deliberate entry layouts, and make role-aware navigation and dashboards easier to scan while retaining existing destinations.
3. Polish checkout progress, summaries, tracking, and operational screens with the same visual language. Keep the embedded Shop map, photo pins, clickable pricing cells, persistent total, and existing selection behavior.
4. Make dense operations tables readable at small widths; retain native forms and explicit destructive confirmations. Use motion only for short visual feedback and respect reduced motion.
5. Verify student, professor, shop-staff, and admin journeys, the four-shop map, mobile widths, and the existing full test suite. Document any environment limits in the final report.

## Applied decisions

- A single presentation stylesheet layers the refreshed tokens and shared components over the existing CSS. The logo asset, brand colors, Jinja templates, and native links/forms stay in place; no frontend framework or external font is added.
- The entry hero uses simple CSS paper shapes and the existing logo. Authentication uses a wider information/form layout on desktop and a single readable column on phones, with optional password visibility. Customer dashboards show role and verification context; staff shop pages give direct, shop-scoped operations paths.
- Checkout retains the current five-step progress and embedded map workspace. Upload selection now names the files chosen before upload. The browser still submits through the existing form and server validation. The existing price cells, map pins, and bottom sheet remain intact.
- Order history, tracking, payment review, processing, account settings, and professor management use consistent status, action, and summary treatments. The latest completed tracking step is indicated in text and with `aria-current`; payment verification and printing decisions remain server controlled.
- Management navigation uses in-page anchors to existing sections. All permission checks and destructive confirmation routes remain unchanged.
