# Interface seams for Access VBA tests

VBA class modules can define interfaces and concrete classes can use `Implements`.
Use that seam to keep business-rule tests fast without hiding the real DAO boundary.

| Boundary | Test double | Required integration proof |
|---|---|---|
| Validation, decisions, transformations | In-memory fake implementing the interface | None when no I/O occurs. |
| Repository or DAO persistence | No fake for the behavior under test | Sandbox test with real reads/writes and cardinality. |
| External process that cannot be sandboxed | Interface-backed fake | Record the omitted integration as explicit risk. |

```vb
' ICustomerRepository.cls
Public Function FindById(ByVal customerId As Long) As Customer
End Function

' CustomerRepositoryFake.cls
Implements ICustomerRepository
Private Function ICustomerRepository_FindById(ByVal customerId As Long) As Customer
    Set ICustomerRepository_FindById = m_Items(CStr(customerId))
End Function
```

The production service receives `ICustomerRepository`, not a concrete DAO repository.
Before adopting the pattern, import one interface, one real implementation, and one fake;
compile in Access and run one atom. If the project's import path cannot preserve interface
classes, use an `Object` seam and record the limitation. Never use a fake merely to avoid
building a legal fixture for a persistence test.
