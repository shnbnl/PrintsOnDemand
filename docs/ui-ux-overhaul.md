# Responsive UI and motion review

Reviewed on 2026-10-04. This change refines the existing Flask/Jinja interface. Colors, logo, favicon, terminology, account roles, URLs, and business rules are preserved.

## Audit and implementation

Baseline: **328 tests passed** before application changes.

| Finding | Improvement |
| --- | --- |
| Large headings, card padding, shadows, and repeated whitespace | Shared spacing, radius, container, and motion tokens; smaller headings and lighter cards |
| Desktop checkout and configuration constrained to a 35rem form | Full-width checkout with adjacent file/fulfillment sections, compact shop selection, and two-column print configuration |
| Long registration and management forms | Paired compatible fields on wider screens; single-column forms on phones |
| Staff order details and shop administration require lengthy scrolling | Two-column sections on desktop with source order preserved on mobile |
| Management tables require sideways scrolling on phones | Labeled professor/staff cards on smaller screens; tables retained on desktop |
| Narrow fulfillment tiles and repeated filenames obscure the main choices | Full-width fulfillment choices; shorter visible file labels that retain filenames for assistive technology |
| No current-section navigation feedback | Server-rendered active states in desktop and mobile navigation |
| Mobile menu remains open after an outside click or Escape | Native disclosure enhanced with outside-click dismissal and Escape returning focus to its trigger |
| Limited upload and submission feedback | Selected-file highlighting, accessible server-error associations, and upload/submission status text |
| Transitions limited to guest entry screens | Consistent native navigation transitions across the shared layout, with a stable brand and short fade/6px arrival |

Touch controls retain comfortable minimum sizes. Inputs use 16px text. Safe-area insets and a viewport-fit setting support notched devices. The mobile menu uses a dynamic viewport height with a conventional viewport fallback. Long references and filenames wrap. Desktop checkout totals stay visible on sufficiently tall screens.

Motion uses 120ms interaction feedback, 180ms state feedback, and 220ms page arrival. Reduced-motion preferences disable nonessential animation. No frontend dependencies were added. Unsupported browsers use ordinary navigation. Native transitions follow the [Chrome cross-document transition guidance](https://developer.chrome.com/docs/web-platform/view-transitions/cross-document); links, redirects, uploads, and form submissions remain browser-managed. Submission feedback does not cancel requests, disable buttons, or remove named action values, and resets on browser history restoration.

## Files changed

- `app/static/css/app.css`: shared design tokens, responsive layouts, controls, management cards, feedback, and reduced motion.
- `app/static/css/entry-transitions.css`: native transition duration, movement, and reduced-motion behavior.
- `app/static/js/app.js`: disclosure dismissal, upload feedback, accessible error associations, and nonblocking submission feedback.
- `app/templates/base.html`: safe-area viewport, shared transition opt-in, and active navigation.
- `app/templates/auth/register.html`: responsive registration form.
- `app/templates/files/upload.html`: associate upload guidance with its control.
- `app/templates/orders/new.html`: shop layout hook and concise visual labels with complete accessible names.
- `app/templates/staff_orders/detail.html`: responsive section layout.
- `app/templates/admin/payment.html`: paired account fields and full-width instructions.
- `app/templates/admin/professor_form.html`: responsive fields.
- `app/templates/admin/professors.html`: labeled mobile table cells.
- `app/templates/admin/staff.html`: labeled mobile table cells.
- `app/templates/shops/edit.html`: responsive management sections and form fields.
- `app/templates/shops/new.html`: responsive shop fields.
- `docs/ui-ux-overhaul.md`: audit, change inventory, and verification record.

## Verification

- Full `python -m pytest`: **328 passed, 0 failures** after implementation; no tests removed or weakened.
- `python -m pip check`: no broken requirements.
- Existing Flask `db upgrade` and `db check` workflow against a separate `master-ui-check.db`: successful; no new upgrade operations detected.
- `git diff --check`: passed.
- Chrome walkthrough: **56 screens/states**, with complete student, professor, and staff flows executed at **390px and 1440px**.
- Layout checks: **360, 375, 390, 412, 430, 768, 1024, 1280, 1366, 1440, 1536, and 1920px**. No page overflow, clipped controls at viewport edges, or missing images detected.
- Browser workflows included guest entry and role preselection, registration errors, login, dashboard, shop list/detail, map fallback, private upload and configuration, checkout/review, online reference submission, onsite payment, confirmation, delivered tracking, history/filter/empty states, professor Faculty confirmation, staff payment verification/processing/physical handoff, professor management, and admin screens.
- Student selections derive Faculty from the approved managed professor. Professor faculty delivery uses that linked managed Faculty as a read-only destination. Other-shop staff still receive 403 for Professor Management.
- Additional checks: keyboard focus, menu Escape/outside click, browser Back, native transitions, reduced motion, JavaScript-disabled navigation/history, Edge login/history, and iPhone 13/Pixel 5 emulation.
- No JavaScript exceptions or unexpected console errors in the completed walkthrough. Expected HTTP errors were deliberately exercised for validation, 403, and 404 screens.

Local QA evidence is in ignored `tmp/master-ui-visual/` (screenshots and `report.json`); the local walkthrough is `tmp/master_ui_walkthrough.py`. It uses an isolated database and upload directory.

## Limits and scope

Native iOS Safari, macOS Safari, and physical Android/iPhone hardware were unavailable. Device emulation verifies layout and touch configuration, not native keyboards, browser chrome, or physical safe-area behavior. Edge coverage is a smoke test; the full workflow runs used Chrome. Google Maps was exercised through its existing fallback interface without a live API key in the isolated fixture; live third-party map rendering was not retested in this change.

No database models, migrations, routes, authentication, authorization, payment calculations or verification rules, professor eligibility/Faculty rules, order state transitions, file-security behavior, or map logic were changed. The development database was not used for browser or migration QA. Changes are left uncommitted and unpushed.
