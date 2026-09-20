# Existing-suite migration checklist

- Declare a session test-mode flag that normal global resets do not clear.
- Route `getdb` to the verified sandbox while the session flag is active.
- Use the complete session lifecycle and final reset contract.
- Remove environment initialization and configuration writes from individual atoms.
- Reserve deterministic fixture identifiers and delete only owned rows.
- Include every required schema field in fixture inserts.
- Inject `DAO.Database` explicitly where the production API supports it.
- Return canonical JSON from public argument-less functions.
- Separate atomic and smoke manifests; keep importable `.bas` files in the source tree.
- Verify mutation cardinality and teardown after both success and failure.

Any unmet item is explicit harness debt with an owner and a concrete correction. Do not
weaken the production guard or assertions to make an existing suite pass.
