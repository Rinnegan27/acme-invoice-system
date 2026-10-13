# User Acceptance Testing (UAT) Case Directory
## System Framework: Multi-Agent Invoice Automation Pipeline
**Database Baseline Constraints:** `WidgetA: 15` | `WidgetB: 10` | `GadgetX: 5` | `FakeItem: 0`

---

## 1. Advanced "Wrong Name" & LLM Auto-Correction Loops
These cases test whether the LLM is capable enough to resolve input variations or if it surfaces an escalation payload for the **VP Review / Reflection Loop**.

### TC-NAME-01: Standard Spacing Discrepancy
* **Input Style:** `Item: Widget A` | `Qty: 5`
* **Intent:** Trailing and intermediate spaces within item catalog names.
* **Expected Logic Path:** **PASS (Auto-Fix).** The validation LLM normalizes the string layout to `WidgetA`. It maps securely against database rules without triggering manual oversight checks.

### TC-NAME-02: OCR Typo Distortion
* **Input Style:** `Item: Widg3tA` | `Qty: 3`
* **Intent:** Leetspeak numeric character replacement simulating classic optical text extraction mistakes.
* **Expected Logic Path:** **FLAG.** Validation layer flags the line item payload as an **Unknown Item**. The system blocks execution to protect database query bounds.

### TC-NAME-03: Plausible but Missing Entry
* **Input Style:** `Item: WidgetC` | `Qty: 2`
* **Intent:** Nomenclature structural match variant completely absent from repository seed scripts.
* **Expected Logic Path:** **FLAG.** Immediate validation boundary catch. System drops workflow transit and posts an official logging record: *"Rejection: Unknown target item entity."*

### TC-NAME-04: Case Variation Normalization
* **Input Style:** `Item: widget_a` | `Qty: 5`
* **Intent:** Conversion of PascalCase constants into lowercase snake_case variants.
* **Expected Logic Path:** **PASS (Auto-Fix).** Internal parsing engines instantly correct configuration format patterns, passing values into standard ledger rules.

### TC-NAME-05: Character Insertion Anomaly
* **Input Style:** `Item: Widgiet B` | `Qty: 2`
* **Intent:** Single character fat-finger text additions introduced during automated invoicing generation.
* **Expected Logic Path:** **PASS (Auto-Fix).** Validation agent applies a fuzzy self-correction loop, identifies the semantic target as `WidgetB`, and flags it fixed.

### TC-NAME-06: High Ambiguity Multi-Collision
* **Input Style:** `Item: W-A` | `Qty: 10`
* **Intent:** Abbreviated strings missing vital unique layout segments.
* **Expected Logic Path:** **VP REVIEW ESCALATION.** The LLM isolates low certainty bounds. It refuses to gamble processing execution and moves parameters to the VP loop for risk review.

### TC-NAME-07: Truncated Suffix String
* **Input Style:** `Item: WidgA` | `Qty: 2`
* **Intent:** Abruptly cropped asset identifiers.
* **Expected Logic Path:** **PASS (Auto-Fix).** Semantic evaluation paths match proximity factors securely to `WidgetA`, altering state layers safely.

### TC-NAME-08: Synonym / Brand Alias
* **Input Style:** `Item: Widget Alpha` | `Qty: 1`
* **Intent:** Commercial descriptive nomenclature mapped against structural warehouse names.
* **Expected Logic Path:** **VP REVIEW ESCALATION.** The system captures proximity to `WidgetA`, but escalates execution tasks to VP review limits to ensure corporate compliance rules hold.

### TC-NAME-09: Interspersed Special Characters
* **Input Style:** `Item: W_i_d_g_e_t_A` | `Qty: 2`
* **Intent:** Deliberate punctuation noise layout introduced to check parsing string sanitization boundaries.
* **Expected Logic Path:** **PASS (Auto-Fix).** The LLM cleanly filters character structure boundaries, mapping the element back to standard `WidgetA`.

### TC-NAME-10: Phonetic / Soundex Deviation
* **Input Style:** `Item: Gadget Ex` | `Qty: 1`
* **Intent:** Whitespace separation of tail identifiers transforming naming parameters into phonetic sounds.
* **Expected Logic Path:** **PASS (Auto-Fix).** Agent models align semantic intention targets dynamically to `GadgetX`, continuing code run workflows.

### TC-NAME-11: Root Pattern Ambiguity Crash
* **Input Style:** `Item: Widget` | `Qty: 5`
* **Intent:** Non-specific primary root classification text missing all final classification metrics.
* **Expected Logic Path:** **VP REVIEW ESCALATION.** System prevents unvalidated guesses between `WidgetA` and `WidgetB`, stopping transaction processing at the VP level.

---

## 2. Advanced "Wrong Number" & Type Coercion Cases

### TC-NUM-01: Fractional Quantities
* **Input Style:** `Qty: 5.5` | `Item: WidgetB`
* **Intent:** Decimal injections targeted at strict hardware database integer column formatting limits.
* **Expected Logic Path:** **FLAG.** Schema parsers intercept input type layout failures before hitting SQL compilation states, treating the object as an data integrity crash.

### TC-NUM-02: Text Representation Conversion
* **Input Style:** `Qty: "Five"` | `Item: WidgetA`
* **Intent:** Text string variables used where math logic expects native digital numerical formats.
* **Expected Logic Path:** **PASS (Auto-Fix).** LLM components analyze language properties, safely transform characters to integer `5`, and verify ledger capacity.

### TC-NUM-03: Negative Arithmetic Exploit
* **Input Style:** `Qty: -10` | `Item: WidgetA`
* **Intent:** Inserting negative numeric entities to create malicious transaction balance modifications.
* **Expected Logic Path:** **FLAG.** Hard mathematical constraint triggers are hit (`Qty < 0`), resulting in system rejection tracking logs.

### TC-NUM-04: Redundant Multi-Format Text
* **Input Style:** `Qty: 10 (Ten)` | `Unit Price: $100`
* **Intent:** Mixing descriptive spelling and literal values together inside a single structural line space.
* **Expected Logic Path:** **PASS (Auto-Fix).** System components isolate the pure numeric value `10` from contextual brackets and clear the file item.

### TC-NUM-05: Approximation Operators
* **Input Style:** `Qty: ~5` | `Unit Price: $50`
* **Intent:** Inserting tilde approximation elements into concrete asset ledger pipelines.
* **Expected Logic Path:** **FLAG.** Enterprise validation tools drop execution paths instantly; approximate allocations cannot pass balance checks.

### TC-NUM-06: Alphabetical Glyph Confusion
* **Input Style:** `Qty: O` | `Unit Price: $200`
* **Intent:** Substituting the string character "O" to trigger unexpected evaluation parameters.
* **Expected Logic Path:** **PASS (Auto-Fix).** Logic steps discover typical character transposition mistakes, normalizing it back to standard numerical integer `0`.

### TC-NUM-07: Percentage Modifiers
* **Input Style:** `Qty: 1,000%` | `Unit Price: $10`
* **Intent:** Using structural unit definitions that break backend arithmetic processing properties.
* **Expected Logic Path:** **FLAG.** Pipeline structural defenses drop execution workflows safely before math evaluation runs are executed.

### TC-NUM-08: Zero-Padding Structural Blocks
* **Input Style:** `Qty: 00005` | `Unit Price: $100`
* **Intent:** Heavy leading numeric padding intended to find memory leak bounds.
* **Expected Logic Path:** **PASS (Auto-Fix).** Python casting processes the parameters to clear numeric single-digit limits (`5`) cleanly.

### TC-NUM-09: Scientific Notation
* **Input Style:** `Qty: 1e1` | `Item: WidgetB`
* **Intent:** Exponential data entries targeting unvetted string casting loops.
* **Expected Logic Path:** **PASS (Auto-Fix).** Typestate management converts expressions to structural integer inputs (`10`), validating database lines safely.

### TC-NUM-10: Unit String Inclusion Noise
* **Input Style:** `Qty: 3 units` | `Unit Price: USD $100.00`
* **Intent:** Affixing contextual description headers immediately adjacent to operational integer blocks.
* **Expected Logic Path:** **PASS (Auto-Fix).** Schema fields parse string blocks clean of alpha data characters, capturing integer variables accurately.

---

## 3. Inventory Stock & Boundary Edge Cases

### TC-STOCK-01: Exact Capacity Match
* **Input Style:** `Item: GadgetX` | `Qty: 5`
* **Intent:** Matching absolute available unit counts down to zero warehouse balance boundaries.
* **Expected Logic Path:** **PASS.** Ledger checks confirm exact asset balance metrics. Workflow stages process to approval queues successfully.

### TC-STOCK-02: Standard Overstock Bounds
* **Input Style:** `Item: GadgetX` | `Qty: 6`
* **Intent:** Exceeding local structural ledger asset values by single items.
* **Expected Logic Path:** **FLAG.** Rejection states process instantly, flagging clear capacity mismatches.

### TC-STOCK-03: Zero Capacity Asset Call
* **Input Style:** `Item: FakeItem` | `Qty: 1`
* **Intent:** Direct transaction actions targeting products sitting locked at absolute zero stock totals.
* **Expected Logic Path:** **FLAG.** System captures product availability issues instantly and aborts active document pipeline runs.

### TC-STOCK-04: Zero Unit Empty Requests
* **Input Style:** `Item: GadgetX` | `Qty: 0`
* **Intent:** Processing transactions that request zero physical assets.
* **Expected Logic Path:** **FLAG.** Corporate audit parameters block zero-unit document processing configurations.

### TC-STOCK-05: Off-By-One Ceiling Overstock
* **Input Style:** `Item: WidgetA` | `Qty: 16`
* **Intent:** Targeting boundary verification code directly past absolute inventory parameters (`15`).
* **Expected Logic Path:** **FLAG.** Intercept paths reject transactions instantly, showing exact ledger checks operate correctly.

### TC-STOCK-06: Duplicated Row Splits
* **Input Style:** `Item: WidgetB (Row 1): 1` | `WidgetB (Row 2): 10`
* **Intent:** Breaking transaction values across multiple items to bypass validation aggregations (`11 > 10`).
* **Expected Logic Path:** **FLAG.** Accumulators unify item data structures, block inventory overstock, and halt system transit operations.

### TC-STOCK-07: Lowercase Casing Matching
* **Input Style:** `Item: widgeta` | `Qty: 15`
* **Intent:** Testing case normalization when reaching absolute maximum warehouse limit values.
* **Expected Logic Path:** **PASS.** Normalization actions adjust text strings successfully while resolving available balance pools.

### TC-STOCK-08: Total Depletion Target Balance
* **Input Style:** `Item: WidgetB` | `Qty: 10`
* **Intent:** Draining active tracking values down to absolute empty system levels.
* **Expected Logic Path:** **PASS.** The ledger accurately accepts transactions matching total active limits exactly.

### TC-STOCK-09: Floating Point Micro-Overflow
* **Input Style:** `Item: GadgetX` | `Qty: 5.0000001`
* **Intent:** Injected float values intended to cheat integer capacity comparisons.
* **Expected Logic Path:** **FLAG.** Precision validation systems intercept processing runs and block storage modifications.

---

## 4. Advanced Compound Enterprise Scenarios

### Scenario 4.1: The Over-Threshold Understock
* **Payload Structure:** `Item: WidgetB` | `Qty: 25` | `Unit Price: $500` | `Total: $12,500`
* **Behavior Matrix:** Triggers multi-stage system parameters simultaneously. The layout price is over the critical **$10,000 threshold**, but warehouse capacity constraints break limits first (`25 > 10`).
* **System Resolution:** Fast-fail logic halts execution inside the validation loop before wasting active token costs inside secondary high-tier approval cycles.

### Scenario 4.2: The Ghost Phantom Total
* **Payload Structure:** `Item: WidgetA` | `Qty: 10` | `Unit Price: $100` | `Total: $11,000`
* **Behavior Matrix:** Product capacity holds safely (`10 <= 15`), but manual invoice pricing computation calculations are completely wrong (`10 * 100 = 1,000`, not `11,000`).
* **System Resolution:** Validation verification loops run separate math proofs, uncover structural pricing changes, and cancel tracking actions instantly before escalation cycles start.

### Scenario 4.3: Sneaky Suffix Typosquatting
* **Payload Structure:** `Item: WidgetA-Premium` | `Qty: 2` | `Unit Price: $4,000` | `Total: $8,000`
* **Behavior Matrix:** Appending tracking variations directly onto warehouse items to force structural processing errors.
* **System Resolution:** Validation tools track SKU variations safely, refuse to drop unknown text attributes blindly, and move files into formal rejection state records.

### Scenario 4.4: The Multi-Item Balancing Act
* **Payload Structure:** Balanced collection containing precise allocations across multiple catalog entries.
* **Behavior Matrix:** Row 1 and Row 3 fit active inventory records, but Row 2 completely breaks stock constraints.
* **System Resolution:** Transactions operate as **atomic tasks**. A solitary line error cancels execution across entire document assets to protect financial states.

### Scenario 4.5: Microcurrency Rounding Vault
* **Payload Structure:** `Item: GadgetX` | `Qty: 3` | `Unit Price: $3,333.3333` | `Total: $10,000.00`
* **Behavior Matrix:** Evaluating fractional math values extending past traditional two-decimal ledger parameters.
* **System Resolution:** Ingestion modules keep numerical data values safe using floating calculations, balancing tolerances perfectly before passing data into VP confirmation engines.

### Scenario 4.6: Script Injection Header Attacks
* **Payload Structure:** `Vendor: '; DROP TABLE inventory; --` | `Item: WidgetA` | `Qty: 1`
* **Behavior Matrix:** Classic injection configurations buried directly inside unstructured text spaces.
* **System Resolution:** Database connection routines utilize parametrized variable sets exclusively. String parameters are safely parsed as raw text variables, preserving database integrity.
---

## 5. User journey (1.8.0+)

Flow: **Capture → Validate → HITL / VP → Pay / Reject.**

| Stage | What happens | Gate |
| --- | --- | --- |
| Capture | Parse file. Raw `Qty` markers (`~`, float) fail closed. Digit SKUs stay raw. | `IngestionFailed`, no stock draw |
| Validate | Catalog, stock (with `prior_items` credit), math, soft findings. | Hard issue → reject |
| HITL / VP | High value (>$10k) or soft finding → human gate or VP agent. | approve / reject / escalate |
| Pay / Reject | `PaymentPermit` (HMAC) is required. LLM text never pays. | Permit or reject |

Offline tests use `Pipeline(human_gate=lambda _inv: "approve" | "reject" | "escalate")`.
Live CLI path (TTY, Grok): `uv run python -m invoice_automation.main --invoice_path=<file> --human-approval`,
then press `a`, `r`, or `e`. Use `--auto-vp` or `GALATIQ_CLI_AUTO_VP=1` to skip the prompt.
Live runs are manual. CI stays on `--llm=stub`.

| TC ID | Journey step | Input | Expected (offline stub) |
| --- | --- | --- | --- |
| TC-HITL-01 | HITL approve (high value) | $10,250 clean | **paid**, actor `human_cli` |
| TC-HITL-02 | HITL reject (high value) | $10,250 clean | **rejected**, "Human rejected" |
| TC-HITL-03 | HITL escalate (high value) | $10,250 clean | **paid** via VP agent (`reflected`) |
| TC-HITL-04 | HITL approve (soft) | `Widget Alpha` | **paid**, actor `human_cli` |
| TC-HITL-05 | HITL reject (soft) | `Widget Alpha` | **rejected** |
| TC-HITL-06 | HITL escalate (soft) | `Widget Alpha` | **paid** via VP agent |
| TC-HITL-07 | No gate when clean | $1,250 `WidgetA` ×5 | **paid**, gate not called |
| TC-HITL-08 | No gate on hard reject | $12,500 `WidgetB` ×25 | **rejected** `insufficient_stock`, gate not called |
| TC-GUARD-01 | Digit SKU reject | `Item: Widg3tA` | **rejected** `unknown_item` |
| TC-GUARD-02 | Qty `~5` fail closed | `Qty: ~5` | **failed**, `invalid_quantity`, no draw |
| TC-GUARD-03 | Float qty fail closed | `Qty: 5.0000001` | **failed**, `invalid_quantity`, no draw |
| TC-GUARD-04 | Widget Alpha soft VP | `Item: Widget Alpha` | soft finding, VP approves, **paid** |
| TC-GUARD-05 | Vendor injection review then pay | `Vendor: '; DROP TABLE inventory; --` | `vendor_injection_review`, VP approves, **paid**, DB intact |
| TC-REV-01 | Revision delta stock | `INV-QTY` WidgetA 3→4, 1 left | **paid**, stock 1→0, `PaymentRevised` |
| TC-REV-02 | Revision beyond shelf | `INV-QTY` WidgetA 3→5, 1 left | **rejected** `insufficient_stock`, stock kept |
| TC-TWIN-01 | Format twin | `invoice_1011.txt` then `.pdf` | both **paid**, one `payment_intent`, no second draw |

Tests: `tests/test_uat_scenarios.py` (section 5), with `tests/test_cli_hitl.py` and
`tests/test_live_guardrails.py` for unit-level checks.
