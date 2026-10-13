# Operator journey (2.0.2)

Follow these steps for each invoice.

1. **Capture.** Run the CLI with the invoice file.
   The system reads the file and extracts fields.
2. **Check the quantity.** `Qty: ~5` and `Qty: 5.5` stop the run. Fix the source file.
3. **Validate.** The system checks the SKU, stock, price, and totals.
   Digit OCR SKUs (for example `Widg3tA`) are hard-rejected — not a VP path.
4. **Scrutiny.** An invoice at or over $10,000 needs approval.
   Soft findings need approval too (`W-A`, `Widget Alpha`).
5. **Decide.** In a TTY, the CLI asks `a / r / e / q`.
   - `a`: you approve. The system pays with a permit.
   - `r`: you reject. The system does not pay.
   - `e`: the VP agent decides.
6. **Skip the prompt.** Use `--auto-vp` or `GALATIQ_CLI_AUTO_VP=1` in CI or pipes.
7. **Pay or reject.** Payment needs an HMAC `PaymentPermit`. LLM text cannot pay.
   In `prod`, a catalog price far off (for example 10x) is `price_mismatch`. It does not pay.
8. **Reconcile.** If the gateway pays but the stock draw fails, the status is `reconcile`.
   The permit stays unused. Open **Reconcile** in the workbench to retry stock or ack.
9. **Revisions.** A new file with the same invoice ID pays only the stock delta.
   Example: `invoice_1004.json`, then `invoice_1004_revised.json` draws only `GadgetX` ×5.
10. **Format twins.** Same data in another file type (`invoice_1011.txt`, then `.pdf`)
    pays once. It does not draw stock twice.

See `docs/uat_test_cases.md` section 5 for the test IDs.
