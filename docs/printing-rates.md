# Print availability and rush pricing

- A saved print price of zero means that paper/color combination is not offered. Customer rate tables show an em dash, offer no selection control for that cell, and server quotations reject it, including forged or stale selections. Staff can set a positive rate to offer it again.
- If any file requests rush printing, the order rush surcharge is a flat PHP 20.00, charged once per order. Delivery is added separately. For example: PHP 100.00 printing + PHP 20.00 rush + PHP 30.00 delivery = PHP 150.00.
- The shop must still enable the Rush Printing service. Legacy rush-fee records can remain in the database, but their saved amount is not used for new quotes. Fee forms cannot change the fixed rush price.
- Existing placed orders keep their saved price and payment snapshots. No database migration or rewrite of existing orders is required.
