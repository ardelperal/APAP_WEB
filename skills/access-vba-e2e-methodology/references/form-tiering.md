# Form tiering — not every form earns the full refactor

Thin forms + extracted helpers + 4-class atoms + UAT cards is the GOLD standard, but it carries an extraction tax. Paying it on a trivial admin form is waste. Tier each form deliberately; the tier is a **decision the user signs off on**, never a silent skip.

## Tiers

| Tier | Forms that qualify | Treatment |
|---|---|---|
| **1 — Full** | High business risk if it breaks, high churn, complex rules, part of the regulated workflow (PC / CDCA / CDCASUB / PCSUB), or shared across gemelos | Thin form + extracted helpers + atoms in all 4 classes (happy/sad/edge/adversarial) + UAT card(s). The full methodology. |
| **2 — Logic-only** | Moderate risk/churn; has a real rule but limited blast radius | Extract the business rule to a helper with at least happy + sad atoms. Skip exhaustive edge/adversarial unless a specific risk warrants. UAT card only if user-observable. |
| **3 — Leave as-is (documented debt)** | Trivial/CRUD-thin, low churn, low risk, internal/admin/throwaway forms with no real rule | Do NOT extract. Record the form + the decision in the capability doc §7 confidence ledger (`Verified-static`) — and the design-debt angle in §3 "Valoración de diseño" — as **documented debt**, so it is a choice, not an oversight. |

## How to classify — ask in order

1. **Blast radius**: if this breaks in production, who is blocked and how bad? (regulated workflow / money / data integrity → Tier 1)
2. **Churn**: how often does this form change? (frequent edits → Tier 1/2 — it will keep breaking without atoms)
3. **Rule complexity**: is there a real decision/validation/transformation, or is it pass-through CRUD? (real rule → at least Tier 2; pure CRUD → Tier 3)
4. **Gemelos**: is the logic shared across PC/CDCA/CDCASUB/PCSUB? (shared → Tier 1; one mistake multiplies by 4)

When two signals disagree, the higher tier wins.

## The one hard rule of tiering

**Tier 3 is documented, never silent.** Every form left untested must appear in the capability doc §7 confidence ledger (marked `Verified-static`) with the tier rationale. The point of the methodology is that the user is calm *because they know what is and isn't covered* — an undocumented gap breaks that calm even if the decision was correct. A Tier 3 form discovered later as "oh, that was never tested" is a process failure even when leaving it untested was the right call.

## Re-tiering

A Tier 3 form that starts changing often, or gains a real rule, is promoted to Tier 2/1 on its next touch. Tiering is reassessed when scope changes — do not treat the first classification as permanent.
