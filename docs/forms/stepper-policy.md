# Form stepper adoption policy

## Decision

Use a stepper only when at least one of these conditions is supported by the current form and a browser audit:

1. The form exposes more than 10 user-editable controls. Count controls inside initially collapsed disclosure sections too; do not count CSRF, other hidden inputs, or submit buttons.
2. The controls form at least three meaningful groups that an operator can complete separately.
3. An earlier group determines which values are valid in a later group, and progressive feedback helps the operator.
4. Measured abandonment exceeds 30% of starts. This is a candidate signal, **not** proof that analytics already exist: require actual start and abandonment counts before using it.

If none applies, keep one scrollable form. A stepper adds navigation and validation work, so a long page alone is not sufficient evidence. Preserve the existing field names, POST contract, validation responses, and any server-side preview or confirmation step unless a separately approved issue changes them.

## Current decision matrix

The measurements in [#822](https://github.com/ardelperal/APAP_WEB/issues/822) are a historical audit, not a live field inventory. Re-run the probe below before implementing a new form or relying on a count.

| Form | Decision | Reason to verify |
|---|---|---|
| `/admin` add user | No | The audited form has three inputs and one group. |
| `/voluntarios/new` | No | The audited form has six inputs and one group. |
| `/entradas/new` | No | The audited form has seven inputs and at most two groups. |
| `/animales/new` | Yes, #823 | The current `AnimalForm` declares 24 fields; group the fields that actually exist, not the old issue's example names. |
| `/entradas/batch/new` | Yes, #824 | The current form has five fixed animal rows and a separate server preview/commit flow; a stepper must not imply that shared fields or dynamic rows already exist. |

## Repeatable browser audit

Use an authenticated Playwright `page` against the actual route at 1440 × 900 and again at a mobile viewport. Select the form being assessed explicitly when a page has more than one form. Record the initial form height, then open any `<details>` inside that form before counting controls so disclosure does not hide complexity from the decision. This probe counts the same kinds of controls on every route:

```python
form = page.locator("main form").first
height = form.bounding_box()["height"]
form.locator("details").evaluate_all("nodes => nodes.forEach(node => node.open = true)")
controls = form.locator("input:not([type=hidden]):not([type=submit]), select, textarea")
visible_count = sum(control.is_visible() for control in controls.all())
required_count = sum(
    control.is_visible() and control.get_attribute("required") is not None
    for control in controls.all()
)
print({"visible_controls": visible_count, "required": required_count, "initial_height": height})
```

Run axe-core on the same authenticated page after opening disclosures and, for a stepper, on **every step**. The project already pins axe-core 4.10.2 in `tests/e2e/test_login_submit_button.py`:

```python
page.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js")
violations = page.evaluate(
    "async () => (await axe.run(document, {runOnly: {type: 'tag', "
    "values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
)
assert not violations, violations
```

If the axe bundle cannot load, the accessibility audit has **not** passed. Keep the field counts, screenshots or browser trace, axe result, and the decision rationale with the adoption issue/PR. Recheck this matrix quarterly and when a form changes materially; do not silently carry forward old counts.

## Ownership and follow-up

An APAP_WEB maintainer with `Maintain` or `Admin` access reviews and signs off on each future stepper adoption in its approved issue or PR. The policy records the decision, not permission to change an existing form's backend behavior.

The original wizard umbrella [#816](https://github.com/ardelperal/APAP_WEB/issues/816) described the split as `#816a` (component), `#816b` (animal form), and `#816c` (batch form). Their delivered issue numbers are [#821](https://github.com/ardelperal/APAP_WEB/issues/821), [#823](https://github.com/ardelperal/APAP_WEB/issues/823), and [#824](https://github.com/ardelperal/APAP_WEB/issues/824), respectively. #821 provides the component; this policy precedes the two form adoptions.
