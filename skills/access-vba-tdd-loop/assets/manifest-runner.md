# VBA manifest and runner contract

The atomic manifest is the source of truth for independently callable test atoms:

```json
{
  "tests": [
    {
      "name": "Customer discount happy path",
      "procedure": "Test_CustomerDiscount_Happy",
      "expect": { "ok": true, "value": 20 },
      "tags": ["customers", "happy"]
    }
  ]
}
```

`procedure` is globally unique, unqualified, argument-less, and returns a JSON string.
The main manifest contains no `*_RunAll`; aggregators belong in a smoke manifest. Slices
reduce COM calls but do not replace atomic registration. Always pass the manifest path
explicitly, validate it before execution, and run only after the human compile gate clears.

The runtime allowlist is an authorization gate, not a test catalog. A missing or empty list
does not restrict execution; a non-empty list restricts execution to its members. A blocked
procedure is reported for a human or configuration owner to decide and is never auto-added.
