# Access VBA TDD loop

1. Add one failing public JSON-returning atom under the importable source tree.
2. Register it in the atomic manifest; keep aggregators in the smoke manifest.
3. Implement the minimum production behavior.
4. Run the source and signature audit, then import only the changed modules.
5. Ask the human to compile the exact `.accdb` and wait for confirmation.
6. Confirm `humanCompilePending:false`, run `validate_manifest`, then run `test_vba`.
7. Read structured failures, correct production or the test contract, and repeat.
8. Refactor only while the behavioral suite remains green.

Use live Dysflow discovery for parameters. A timeout is not a failed assertion: retry with
bounded output, inspect owned operations, and never terminate an unrelated Access process.

For expensive areas, expose a narrow `Test_<Area>_<Slice>_RunSlice` that returns compact
counts plus the first failure. Keep all atomic entries in the manifest even when a slice is
used to reduce COM round trips.
