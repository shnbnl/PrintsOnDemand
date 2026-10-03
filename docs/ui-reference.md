# UI/UX reference

## Primary reference and availability

**PrintsOnDemand Mobile.pdf** is the primary reference for the existing student-facing UI, navigation, screen flow, terminology, and layout. Preserve its overall concept and navigation during later implementation; improve it where finalized requirements require changes.

All **9 pages** have now been rendered and visually reviewed, with extracted text used to cross-check labels and amounts. The reviewed PDF is now at [docs/references/PrintsOnDemand Mobile.pdf](references/PrintsOnDemand%20Mobile.pdf); it was at the repository root during the original review. Stage 1 does not alter the PDF.

This review records visible mockup content separately from future requirements in the [project specification](project-specification.md). A static PDF does not establish working navigation, uploads, payments, or backend behavior. This follow-up updates documentation only and does not implement or redesign the UI.

## Screen inventory in PDF order

Page numbers are PDF page positions, starting at 1.

| Page | Screen/state | Major sections and components shown |
| --- | --- | --- |
| 1 | Login | Large centered Prints On Demand printer logo; rounded `Username` and `Password` fields; navy `Log-in` button; underlined `Sign in` at upper right. No registration screen or explanation of the `Sign in` destination. |
| 2 | Shop discovery | Map around Mapua Malayan Colleges Laguna; `User Location` marker; four shop cards and map pins; `Search Printing Shop` field with search/direction-style icons; back arrow. Cards show images/logos, names, hours, and services. This is a map with cards, not a separate conventional list screen. |
| 3 | Selected shop and pricing | Map remains behind a large right-side Blue and Silver Bookstore panel. Circular shop photo, name, hours, four highlighted stars and `4 OUT OF 5`, `Pricelist:` table, and large `Proceed` action with arrow. |
| 4 | File selection | Cream background, back arrow, `Select files to print:`, large `Files` control with folder icon, muted `Proceed`, and `Check input files`. No filename list, upload progress, or success message. Muted styling alone does not establish a disabled action. |
| 5 | Printing and claiming choices | Navy background and back arrow. Left: `Select option:` with Regular Printing and Rush Printing/Priority. Right: `Select Claiming Method :` with Direct-to-Professor, Scheduled Pick-up, and Delivery (via Lalamove). Large rounded white cards, service icons, and added charges for rush/professor options. |
| 6 | Professor branch and customization | Upper option groups remain, with professor card shaded gray. Lower left: professor heading, `Insert email:`, blank `Sender Email:` and `Reciever Email:` fields. Lower right: cream customization panel, file tabs/add-files action, paper sizes, color, quantity stepper, and `Proceed To Payment`. |
| 7 | Pickup branch and customization | Same upper groups, with Scheduled Pick-up shaded gray. Lower left: pickup heading and five slots under `Select Time of Pick-up`. Same customization panel and payment action at right. |
| 8 | Delivery branch and customization | Same upper groups, with Delivery (via Lalamove) shaded gray. Lower left: delivery heading and five slots under `Select Time of Delivery`. Same customization/payment panel at right. No address or courier-booking form is visible. |
| 9 | Price summary and QR payment | Back arrow; central blue column with `PRICE SUMMARY`; white rounded card showing shop, `Paid`, service charges, filenames/amounts, and total. Below: QR image with InstaPay mark and `SCAN FOR PAYMENT`. No subsequent screen is supplied. |

### Flow represented by the pages

**Login (1) -> map/shop discovery (2) -> selected shop/pricelist (3) -> file selection (4) -> printing priority and claiming method (5) -> one branch with customization (6, 7, or 8) -> price summary/QR payment (9).**

Pages 6-8 are alternatives, not three consecutive steps every student completes. The shaded claiming card matches the branch details below it; this suggests selection visually but does not prove implemented interaction. The reference places file customization after the initial printing/claiming choices, rather than on a separate earlier screen.

Back arrows appear on pages 2-9. Forward labels are `Proceed` on pages 3-4 and `Proceed To Payment` on pages 6-8. Exact back destinations, option-card transitions, submission timing, and navigation after page 9 are not specified.

## Shop information and sample prices

Page 2 shows these example shops:

| Shop | Hours shown | Offers shown |
| --- | --- | --- |
| Blue and Silver Bookstore | 6:00 AM - 5:00 PM | Direct-to-Professors, Pick-up |
| Iced Design and Prints | 9:00 AM - 3:00 PM | Direct-to-Professors, Pick-up, Rush Printing |
| CHALECOSPOT | 8:30 AM - 6:50 PM | Pick-up, Rush Printing |
| Pixels Print and Press | 9:00 AM - 5:00 PM | Pick-up, Rush Printing |

Page 3 shows Blue and Silver Bookstore's sample pricelist:

| Paper Size | Grayscale/page | Colored/page |
| --- | --- | --- |
| Letter | ₱2.00 - ₱3.00 | ₱5.00 - ₱10.00 |
| Legal | ₱4.00 - ₱5.00 | ₱7.00 - ₱12.00 |
| A4 | ₱3.00 - ₱4.00 | ₱5.00 - ₱10.00 |
| A3 | ₱9.00 - ₱12.00 | ₱14.00 - ₱35.00 |

Pages 5-8 show `ADD ₱25.00` for Rush Printing/Priority and `ADD ₱20.00` for Direct-to-Professor. These amounts, hours, shop details, and rating are reference content, not verified live data or approved production configuration. Final pricing remains undecided and must come from database/settings records.

## Shared customization and scheduling

Pages 6-8 repeat these components:

- Tabs/actions: `File 1`, `File 2`, `Add files +`, and `Customize`; the first file tab appears active. The layout suggests per-file configuration but does not establish how settings are persisted or scoped.
- `Paper Size:` choices: Letter (8.5 x 11), Legal (8.5 x 14), A4 (8.27 x 11.69), A3 (11.69 x 16.54), and A2 (16.5 x 23.4), as displayed. A2 has no corresponding row in the page 3 pricelist.
- `Print Color Output:` choices `Greyscale` and `Colored`.
- `Print Count:` minus/value/plus stepper showing `1`. The PDF does not define copies versus pages or page-count calculation.
- Rounded `Proceed To Payment` action with a circled right arrow.

Pickup (page 7) and delivery (page 8) both show `10:00 AM - 11:00 AM`, `11:00 AM - 12:00 NN`, `1:00 PM - 2:00 PM`, `2:00 PM - 3:00 PM`, and `3:00 PM - 4:00 PM`. No date selector, capacity/availability feedback, selected-slot example, or delivery address is shown. These are sample slots, not fixed operational availability.

## Terminology recorded from the PDF

| Area | Source labels |
| --- | --- |
| Account | `Username`, `Password`, `Log-in`, `Sign in` |
| Discovery | `Search Printing Shop`, `User Location`, `Offers:`, `Opens`, `Open:`, `4 out of 5`, `Pricelist:` |
| Upload | `Select files to print:`, `Files`, `Proceed`, `Check input files` |
| Printing/claiming | `Select option:`, `REGULAR PRINTING`, `RUSH PRINTING/PRIORITY`, `Select Claiming Method :`, `DIRECT-TO-PROFESSOR`, `SCHEDULED PICK-UP`, `DELIVERY (VIA LALAMOVE)`, `ADD` |
| Professor | `Insert email:`, `Sender Email:`, `Reciever Email:` (source misspelling) |
| Customization | `File 1`, `File 2`, `Add files +`, `Customize`, `Paper Size:`, `Print Color Output:`, `Greyscale`, `Colored`, `Print Count:`, `Proceed To Payment` |
| Scheduling | `Select Time of Pick-up`, `Select Time of Delivery`, `12:00 NN` |
| Summary/payment | `PRICE SUMMARY`, `Paid`, `View Mode of Delivery:`, `Rush Printing`, `Direct-to-Professor`, `View Files:`, `TOTAL:`, `SCAN FOR PAYMENT` |

Shop cards use plural `Direct-to-Professors`, while claiming uses singular `Direct-to-Professor`. The pricelist uses `Grayscale/page`, while customization uses `Greyscale`. `Log-in` and `Sign in` coexist without an explanation of their different purposes. These are recorded source inconsistencies, not newly finalized application copy.

## Existing Direct-to-Professor behavior

Direct-to-Professor appears as a claiming method with a paper-plane icon and sample ₱20 surcharge (pages 5-6). Page 6 requests manually typed sender and receiver emails beside file customization and leads toward payment. Page 9 includes the service as a charge.

There is no Myself/Professor recipient selector, professor search, approved-professor dropdown, name/department/office display, approval indicator, optional note, send-success message, or professor receipt confirmation.

The fields/icon suggest an email-oriented concept, but the PDF does not establish whether documents, printed copies, notifications, or some combination are sent. Physical versus electronic professor fulfillment remains an open specification decision. This review does not define a delivery mechanism or authorize automated email sending.

## Existing payment and price-summary behavior

Page 9 shows Blue and Silver Bookstore with `Paid` and this example:

| Section | Item | Amount |
| --- | --- | --- |
| View Mode of Delivery | Rush Printing | ₱25 |
| View Mode of Delivery | Direct-to-Professor | ₱20 |
| View Files | Technopreneurship.pdf | ₱40 |
| View Files | G3.pdf | ₱180 |
| Total | All four items | ₱265 |

The arithmetic is consistent: 25 + 20 + 40 + 180 = 265. The basis of each file price (pages, copies, paper, color) is not shown. `View Mode of Delivery` groups printing priority with professor fulfillment. Blue and Silver Bookstore's earlier card does not advertise rush printing, although the summary includes it; shop-supported services require later validation.

The QR scan prompt and `Paid` appear simultaneously. The PDF does not explain whether this is a before-payment screen, an after-payment screen, or combined mockup states. `Paid` is not evidence of actual verification or order submission.

No explicit Online Payment/Onsite Payment selector, instructions beyond scanning, receipt upload, pending/verified progression, order reference, submission confirmation, tracking, or history is shown. The InstaPay mark does not establish a working provider integration or approved merchant QR; the depicted code must not be assumed usable for production.

## Baseline to retain

Keep these concepts and navigation foundations during later implementation, while adding the required behavior below:

- Prints On Demand branding/printer motif; navy/blue, white, and cream palette; rounded cards/controls, prominent headings, icons, and back/forward arrows.
- Login entry, map-based shop search/location/cards, and shop details/pricelist panel retaining map context. The rating display belongs to the visual reference; no review-management system is specified by it.
- File selection/checking, printing priority and claiming choices, branch details, file customization, and onward price/payment summary.
- Regular/rush printing, pickup scheduling, delivery, and the Direct-to-Professor service concept. `Via Lalamove` records source terminology, not a commitment to courier API integration.
- File tabs/add-files affordance, paper/color/quantity controls, and time-slot selection concepts, populated with supported options and real availability later.
- Itemized shop/file/service summary and QR payment affordance, with actual values supplied by configuration.

These are preservation requirements, not a new layout proposal. Pages 1-5 and 9 are landscape compositions; pages 6-8 are taller compositions exposing branch details below the initial choices. Despite the filename, responsive behavior and a complete narrow-screen adaptation are not specified.

## Required extensions mapped to the specification

| Requirement | Existing reference | Required later extension |
| --- | --- | --- |
| Approved professor dropdown | Manual receiver email on page 6 | Add Myself/Professor selection. For Professor, replace free-text receiver email with a searchable dropdown containing only active, approved professors. Revalidate eligibility server-side; no receiver-email override. Retain the Direct-to-Professor service concept. |
| Professor information | Sender/receiver email fields only | Automatically display read-only professor name, department, email, and office/room; allow an optional note. Respect admin approval/revocation. The sender field is not a substitute for authenticated identity or recipient selection. |
| File and order confirmation | `Check input files`; no success state | Confirm successful file validation/storage separately from successful persisted order submission. Give the order a unique reference and explicit confirmation; provide failure/retry feedback. Selected filenames and the summary do not prove submission. |
| Online Payment | QR scan prompt and unexplained `Paid` | Add an explicit Online Payment choice, configurable instructions/QR, and optional private receipt upload. Show pending/verified payment accurately after manual staff verification. No real GCash/Maya APIs initially. |
| Onsite Payment | Not shown | Add an explicit Onsite Payment choice and outstanding/collected state under the finalized collection policy. Do not require QR payment or automatically mark the order paid. |
| Order status tracking | Not shown | Track the persisted order/reference, with payment state separate from fulfillment. Distinguish printing, pickup readiness, dispatch, receipt, and completion; include cancellation/rejection when applicable. |
| Order history | No screen or entry point | Add access to the student's own prior orders with reference, details, price, payment, and fulfillment status. Navigation placement remains for the UI stage. |
| Configurable pricing/options | Static ranges, fees, example total | Read prices/options from database/settings, calculate totals server-side, and retain the accepted price snapshot. Resolve A2 pricing and shop/service inconsistencies without adopting sample amounts as final. |
| Staff/Admin workflows | Student screens only | Later add specified dashboards for order processing, payment verification, progress, users, shops, pricing, professors, and approvals. No dashboard layouts are inferred from this PDF. |

Tracking must use the specification's statuses: `SUBMITTED`, `PAYMENT_PENDING`, `PAYMENT_VERIFIED`, `PRINTING`, `READY_FOR_PICKUP`, `OUT_FOR_DELIVERY`, `SENT_TO_PROFESSOR`, `DELIVERED`, `COMPLETED`, `CANCELLED`, and `REJECTED`. These are not one mandatory linear sequence. File upload success is separate, and professor dispatch is not confirmed receipt.

## Remaining interpretation questions for later stages

- `Sign in` destination, precise back behavior, and when order submission occurs relative to payment.
- Professor fulfillment/receipt mechanism and how the recipient selector relates to claiming methods.
- Per-file settings/count rules, supported paper sizes, price-range basis, and shop service availability.
- Scheduling dates/capacity, delivery destination collection, courier responsibilities, and final fees.
- Payment verification and onsite collection policy; the simultaneous `Paid` and QR prompt settles neither.

The actual PDF review is complete. These questions and extensions are recorded for later stages. No application functionality or UI redesign is included in this follow-up.

## Stage 16 implementation note

The PDF's claiming-method cards and pickup/delivery slot lists inform the implemented checkout choice. New orders now require one shop-supported method: Direct-to-Professor, Scheduled Pickup, or Delivery. Pickup and delivery collect dates as well as slots; the PDF shows slots only. The server validates both against configured Philippine-time windows and shop hours. Delivery additionally records recipient name, phone, and address and uses the shop's configured delivery fee. The order stores these details and fee as historical snapshots, displayed at review, confirmation/tracking, history, and staff detail. The PDF's “via Lalamove” wording remains reference terminology; Stage 16 does not book a courier. Direct-to-Professor still uses an approved professor dropdown, and online/onsite payment retains its separate manual state. The earlier screen inventory and future-looking questions above remain a record of what the original PDF did and did not show.

## Stage 19 UI alignment

The nine PDF pages remain the visual reference. The implemented student journey follows the same broad order: login, map/list shop discovery, shop details and live pricelist, file selection and independent print settings, claiming method, review and itemized price summary, then payment. Rounded cards, navy and cream surfaces, prominent forward actions, and highlighted selection states were already present before this pass. The registered-shop map and selected-shop panel retain the map-plus-details concept from pages 2–3.

This pass makes the shop-detail action lead clearly to **file selection**, distinguishes unselected files from the current order draft, and shows read-only name, department, office, and email details for the approved professor selected as the intended recipient. Pickup and delivery fields remain conditional on the selected method. The order detail keeps the reference, historical file/price snapshots, current fulfillment, next step, and recorded tracking in separate scannable cards. Student history, staff orders, and admin/staff payment review now use the same payment and order badges. **Payment submitted — awaiting verification** has a distinct treatment from **Payment verified**; the order detail no longer presents an old order as a new payment success. A keyboard skip link, local printer favicon, and narrower-screen staff-card layout improve navigation and readability.

Intentional differences from the PDF remain: approved-professor selection replaces manual recipient email; shop/pricing/fees come from the database rather than sample amounts or ratings; Google Maps displays registered shops without Places; delivery is a shop request rather than an automatic Lalamove booking; QR/reference submission does not mark a payment paid; onsite payment stays pending until recorded by an authorized process. The PDF has no persisted confirmation, verified payment state, tracking, history, or staff/admin screens, so these retain their Stage 0–18 behavior and the shared visual language. Production file storage, courier/payment integrations, deployment, and future stages remain outside this UI pass.
