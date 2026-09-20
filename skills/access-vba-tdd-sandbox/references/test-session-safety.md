# Test session safety

## Required lifecycle

Run one complete session in this order:

```text
BeginTestSession
  → validate the sandbox
  → invalidate database caches
  → set test mode
  → Test_EVE(True)
  → execute fixtures and test atoms
  → Test_EVE(False)
  → EndTestSession
  → ResetTestSession
```

`Test_EVE` is called exactly twice by the lifecycle boundary, never by ordinary atoms.
`BeginTestSession` and `EndTestSession` are the canonical names. Use `SuiteSetup` and
`SuiteTeardown` only when an existing public entry point must remain callable; each alias
delegates directly to its canonical operation and owns no additional behavior.

## Complete `ResetTestSession` contract

The final reset is idempotent and attempts every cleanup even if an earlier cleanup fails:

1. Close and clear the project's cached `getdb` handle.
2. Close and clear the test database handle.
3. Set the test-mode flag to `False`.
4. Clear the sandbox path and password variables.
5. Remove `BackendPathSandbox`, `BackendPathConfigurado`, and `DatosEnLocal` TempVars.
6. Clear test-only fixture state and application caches populated by the session.
7. Preserve and return cleanup errors as diagnostics; never leave test mode active silently.

`ResetGlobals` must not clear the session test-mode flag during setup. The lifecycle owns
that flag so cache invalidation cannot accidentally route a running test back to production.

## Six checks that block production

Before setting test mode or opening a writable database, require all six checks:

1. The configured sandbox path is present and resolves to one unambiguous file.
2. The path is local and is not UNC or another prohibited shared production location.
3. The normalized path differs from every configured production backend path.
4. The filename or schema contains the project-specific sandbox fingerprint.
5. The file exists and opens through DAO with the configured credentials.
6. A read-only identity probe confirms the expected sandbox marker and no production marker.

Any failure returns `TESTS BLOCKED`, leaves test mode false, closes provisional handles, and
performs no seed, delete, update, or insert.

## Temporary `.accdb` injection proof

Use a fresh file under the process temp directory when a test must prove that a repository
honors an injected `DAO.Database` instead of calling `getdb` internally:

1. Start a verified sandbox session and reserve an identifier absent from the sandbox.
2. Create a unique temporary `.accdb` and only the minimal required schema.
3. Invoke the production method with the temporary database explicitly.
4. Assert the expected row and values exist in the temporary database.
5. Assert the same identifier is absent from the persistent sandbox.
6. Close both handles, delete the temporary file, end the session, and reset all state.

Both assertions are mandatory. A positive assertion only in the temporary file does not prove
that the method avoided a second write through `getdb`; the negative sandbox assertion closes
that gap.
