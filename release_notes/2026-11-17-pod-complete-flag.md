---
id: 2026-11-17-pod-complete-flag
title: A CLIN can be marked POD complete
published: false
publish_date: 2026-11-17
tags: [improved, contracts]
critical: false
---

A CLIN can be marked POD complete. The mark is stored on the CLIN. It is allowed only when the CLIN has at least one shipment and every shipment has a POD date. If the shipped quantity is still under the order quantity, the mark is still saved and you get a warning. Adding a shipment that has no POD date, clearing a POD date, or removing the last shipment clears the mark.

Finance Audit shows a POD Date column right after Ship Qty. Click the date on a CLIN row, or Manage shipments next to + cost, to open a shipments window. The window lists each shipment's quote value, paid, item value, and customer pay, in the order the shipments were added. You can enter Paid and Customer Pay while adding a shipment. Quote and item value still fill in from the quantity and the CLIN unit prices, and you can see that preview as you type the quantity. Editing a shipment quantity updates quote value and item value from those same prices (110 at $68.00 is $7,480.00; 110 at $79.97 is $8,796.70). Paid and Customer Pay stay on the ledger and do not change with quantity. A quantity that did not change leaves the stored amounts alone, and older rows are not rewritten until the next quantity edit. If a CLIN price is missing, that side is left as stored. Changing those dollar amounts by hand still happens on Finance Audit or the CLIN page, and a hand-entered amount is replaced the next time the quantity changes. A blank shipment name shows up as Shipment 1, Shipment 2, and so on, counting every shipment on the CLIN in the order they were added, including ones that have a name. Changing a ship date does not renumber them. Removing one does renumber the later blank names. The same window opens from Manage shipments on a contract's CLIN card, and from Manage shipments on the CLIN page, which opens the shipment list. Closing it reloads Finance Audit and the CLIN page. On the contract page it refreshes the CLIN card you have open. If the shipments window is already open, the next button loads that CLIN in the same window. The Complete Shipping button is gone from the CLIN page. Ship quantity and ship date already follow the shipments. The older shipment popups are still in the app until a later cleanup.

The POD Complete box is in the window, and it stays off until every shipment has a POD date. The Finance Audit page reloads once when you close the window, so the sections you have open stay put while you edit.

Adding or editing a shipment now happens in one form inside that window. On the CLIN page the shipment rows are read-only, and Edit opens the window on that shipment. The CLIN POD date comes from the shipments, so you cannot type over it while shipments exist. Creating a shipment and its payment rows saves together: if the payment write fails, the shipment is not left behind. The older shipment popups are still in the app until a later cleanup.

Edit Paid and Customer Pay from the shipments popup. Edit on a shipment now shows Paid and Customer Pay filled in with the current totals. Type the new total and save. The change is recorded as one adjustment in payment history. Type 0 to clear a total. On a CLIN that has shipments, the CLIN Paid and Customer Pay are the sum of the shipments and can only be changed on the shipments.

Payment Activity now shows shipment payments. On Finance Audit, the Payment Activity list includes payments entered on shipments, labeled with the CLIN and the shipment name.
