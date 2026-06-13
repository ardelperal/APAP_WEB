# Legacy Technical Area — Admin Panel and System Configuration

> **Excluded from product scope.** This is a legacy Access administration area, not a business feature. It will not be migrated as a product feature. The permissions model (per-form/per-button passwords) should be replaced by a proper RBAC system in the web application.

### Why this is excluded

| Concern | Legacy approach | Web replacement |
|---------|----------------|-----------------|
| Access control | Per-form/per-button passwords via `TbOpciones` | Role-based access control (RBAC) |
| Strict mode | Toggle in `m_ObjEntorno.BaseEnModoEstricto` | Application setting if needed; confirm behavior first |
| Report management | Form-based SQL editor | Report definition service with validation |
| Materials | Form-based catalog | Standard catalog CRUD (covered in feature-04) |

## Legacy entry point

`Form0PanelDeControl` is an administrator-oriented start/control panel for the Access application.

Exported files:

- `src/forms/Form_Form0PanelDeControl.form.txt`
- `src/forms/Form_Form0PanelDeControl.cls`

Caption observed: `Menú de Opciones Administrador`.

The form is password-protected on open, using either `TbOpciones` or the administrator password stored in `m_ObjEntorno.ClaveDelAdministrador`.

## Navigation map

| Control / event | Target | Feature | Purpose | Notes |
|---|---|---|---|---|
| `lblEstablecerPermisos_Click` | `Form0ClavesGestion` | Permissions / access control | Manage per-form/per-button passwords | List screen leads to `Form0ClavesAlta` and `Form0ClavesEdicion` via pipe-delimited `OpenArgs` (`formulario|boton`). |
| `lblCambiarModoFuncionamiento_Click` | Inline toggle | System configuration | Toggle strict/non-strict mode | Updates `m_ObjEntorno.BaseEnModoEstricto` and calls `CambiarTitulos()`. |
| `lblCrearInformes_Click` | `FormInformesGestion` | Report management | Manage stored SQL reports | List screen leads to `FormInformeAlta` / `FormInformeEdicion`; uses `Informe` class and `TbInformes`. |
| `lblMateriales_Click` | `FormMaterialGestion` | Materials / inventory | Manage material catalog | List screen leads to `FormMaterialAlta` / `FormMaterialEdicion`; uses `TbMaterial`. |
| `cmdSalir_Click` | Close form | Exit | Close administrator panel | No child feature. |

## Feature: permissions management

Screens:

- `Form0ClavesGestion`
- `Form0ClavesAlta`
- `Form0ClavesEdicion`

Backing table:

- `TbOpciones`

Likely key fields:

- `Formulario`
- `NombreBoton`
- `psw`

Domain behavior:

- Passwords can be configured per form and per button/control.
- `FormularioClave()` checks whether the current form/action requires a key.
- If protected, the user is prompted for a password before continuing.
- `Sistema` class implements create/edit/delete behavior for keys.

Web migration implication:

- Replace form/button password prompts with role/permission policies.
- Preserve the ability to protect specific actions, not only whole pages.
- `TbOpciones` is a legacy permissions table, not a final auth model.

## Feature: strict mode toggle

Legacy behavior:

- The admin panel toggles `m_ObjEntorno.BaseEnModoEstricto`.
- Form captions are updated through `CambiarTitulos()`.
- Non-strict mode appears as a visible title/caption state across forms.

Open questions:

- What exact behavior changes besides captions?
- Is strict mode a safety mode, a permissions mode, or only a visual/operator mode?

Web migration implication:

- Model this as an explicit application setting only after confirming the behavior.
- Do not reduce it to a cosmetic flag until all usages are inspected.

## Feature: report management

Screens:

- `FormInformesGestion`
- `FormInformeAlta`
- `FormInformeEdicion`

Backing table:

- `TbInformes`

Likely fields:

- `IDInforme`
- `Nombre`
- `Descripcion`
- `SQL`

Domain behavior:

- Users can create, edit, delete, test, and export saved SQL reports.
- The `Informe` class wraps report persistence.
- The report test/export flow likely uses shared helpers such as `Consulta` and `GenerarConsultas`.

Web migration implication:

- This is a dynamic reporting feature, not just static reports.
- Stored SQL needs special treatment: permissions, validation, migration to views/query builder, or curated report definitions.

## Feature: materials / inventory

Screens:

- `FormMaterialGestion`
- `FormMaterialAlta`
- `FormMaterialEdicion`

Backing table:

- `TbMaterial`

Likely fields:

- `IDMaterial`
- `Material`
- `Color`
- `Tamaño`
- `Observaciones`

Domain behavior:

- Users can list, search, create, edit, and delete materials.
- Duplicate detection appears to use the combination `Material + Tamaño + Color`.
- Implementation uses direct DAO manipulation rather than a dedicated service class.

Web migration implication:

- Model as a catalog/inventory module.
- Preserve duplicate validation as a unique constraint or domain validation.

## Cross-cutting patterns observed

- Pipe-delimited return convention: `status|successValue|errorValue`.
- Per-action password checks through `FormularioClave()`.
- Open form checks through `FormularioAbierto()`.
- Runtime form resizing via `AjustarTamaño Me`.
- List headers via `ColocarTituloEnFiltro`.
- Excel export helper through `GenerarConsultas`.
- Generic lookup helpers such as `Dame()` and `DameID()`.
- Strict mode captions through `m_ObjEntorno.BaseEnModoEstricto` and `CambiarTitulos()`.

## Suggested business-feature discovery order

1. Animal records (`FormFichaAnimal*`) — core entity and lifecycle.
2. Intake / entry (`FormEntrada*`, `FormEntradasMultiples`, `FormCesionPorPropietario`).
3. Foster care (`FormAcogida*`, `FormCasaAcogida*`).
4. Adoption (`FormAdopcion*`, `FormAdopcionesGestion`).
5. Health records (`FormFichaSanitaria*`, therapies, recommendations, desparasitation).
6. Reports and templates (`FormInformes*`, `FormInformeTrimestral`, `Plantilla`, `Resumen`).
7. Attachments (`FormAnexos`) as reusable document hub.
