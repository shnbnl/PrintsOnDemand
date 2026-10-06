# Responsive UI and account recovery

The Shop checkout step now presents search and a list first. Selecting a shop collapses the picker; **Change shop** reopens it with the query intact. The map is optional on mobile and the list remains usable if Maps fails. The print form follows the map in normal page flow with one page scrollbar. Switching shops retains files and compatible settings; unavailable paper/output combinations or rush are replaced with an explicit notice, and the server recalculates the quote. Paper and output have direct controls, with the selected shop's stored rate table under **View shop rates**. Document page counts appear only when known; Word files need an available server converter for dependable counting.

The compact mobile header and Shop step were reviewed at 320, 360, 390, 430, 768, 1024, and 1440 pixels using local fixtures. Fulfillment, payment, review, shop discovery, order history, and staff rules remain server-authoritative. Customer-facing order timestamps display Philippine time; persisted timestamps remain UTC.

Public visitors can preview active shop descriptions, addresses, hours, and services at `/shops/preview`. That page has no customer files, orders, or protected actions. Shops or rates marked as sample remain marked. Shop owners must confirm sample information and prices before real use. The public landing page explains actual upload visibility and cleanup eligibility. `SUPPORT_EMAIL` adds a support link only when the owner supplies a real mailbox.

## External setup

Set `GOOGLE_MAPS_API_KEY` and `GOOGLE_MAPS_MAP_ID` in the deployment environment. Production has no default map ID. Configure the browser key for the deployment's approved website referrers and the Maps JavaScript API, and enable the API and billing in the Google Cloud project. Google's [setup guide](https://developers.google.com/maps/documentation/javascript/get-api-key) describes production keys and notes that its Demo Key is for testing/prototyping. Review [quota and billing](https://developers.google.com/maps/documentation/javascript/usage-and-billing) before launch; an exceeded limit can stop map loads. The shop list is the fallback if Maps is unavailable. The location control asks permission only after a user action. The app does not infer distances without location data.

Password recovery requires the new database migration plus `PASSWORD_RESET_BASE_URL`, `MAIL_HOST`, `MAIL_PORT`, `MAIL_FROM`, and, when needed, `MAIL_USERNAME`/`MAIL_PASSWORD` and `MAIL_USE_SSL`. `PASSWORD_RESET_BASE_URL` must be the canonical HTTPS site origin in production. Student and professor reset links expire after 30 minutes and can be used once. Requests receive a generic response and are limited per address and direct peer IP in a one-hour window. Configure and verify a real SMTP service in deployment; local tests stub email delivery and do not prove external delivery. Without those settings, no reset message is sent. Shop staff account recovery remains an administrator-managed process.

The owner still needs to supply a verified support address, real shop/rate information, and working Google Maps and SMTP configuration. No production data, orders, payments, or credentials were used for this pass.

## Local browser captures

These captures used isolated accounts, shops, synthetic PDFs, and a mocked Maps JavaScript response for the map view. The fallback capture disables Maps entirely. No payment or real order was submitted.

- [Landing at 320px](screenshots/responsive-ui/landing-mobile.png) and [1440px](screenshots/responsive-ui/landing-desktop.png)
- [Selected-shop checkout at 390px](screenshots/responsive-ui/shop-mobile.png) and [1440px](screenshots/responsive-ui/shop-desktop.png)
- [Review at 390px](screenshots/responsive-ui/review-mobile.png), [history at 390px](screenshots/responsive-ui/history-mobile.png), and [Maps fallback at 390px in a short viewport](screenshots/responsive-ui/map-fallback-mobile.png)
