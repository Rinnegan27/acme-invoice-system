# Case brief scenario proof

This file is generated. Do not edit by hand.

- Engine: offline stub (--llm=stub)
- Passed: 8/8
- ok: True
- Source brief: https://github.com/galatiq-ai/galatiq-case-invoices

| Scenario | Invoice | File | Expected | Actual status | Issues | Pass |
|---|---|---|---|---|---|---|
| Normal order within stock | INV-1001 | `invoice_1001.txt` | paid | paid | — | yes |
| Normal order within stock | INV-1004 | `invoice_1004.json` | paid | paid | — | yes |
| Normal order within stock | INV-1006 | `invoice_1006.csv` | paid | paid | — | yes |
| Quantity exceeds stock | INV-1002 | `invoice_1002.txt` | rejected + `insufficient_stock` | rejected | insufficient_stock:GadgetX | yes |
| Fraudulent / zero-stock item | INV-1003 | `invoice_1003.txt` | rejected + `zero_stock` | rejected | zero_stock:FakeItem | yes |
| Item not in database | INV-1008 | `invoice_1008.txt` | rejected + `unknown_item` | rejected | unknown_item:SuperGizmo, unknown_item:MegaSprocket | yes |
| Item not in database | INV-1016 | `invoice_1016.json` | rejected + `unknown_item` | rejected | unknown_item:WidgetC | yes |
| Invalid data | INV-1009 | `invoice_1009.json` | rejected + `invalid_quantity` | rejected | invalid_quantity:WidgetA, negative_amount, missing_vendor | yes |

Regenerate with:

```bash
make scenario-proof
```
