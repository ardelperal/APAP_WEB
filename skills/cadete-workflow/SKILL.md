---
name: cadete-workflow
description: Trigger: Cadete PR workflow, state transitions. Flujo de estados para PRs e Issues en GitHub. Trigger: cambiar estado de PR/issue, rechazar, aprobar, mergear, registrar histórico.
license: Apache-2.0
metadata:
  author: cadete-team
  version: 1.0
  last_verified: 2026-09-05
  scope: ['cadete']
  auto_invoke: ['working on Cadete workflow']
  tiers: ['cadete']
---



## Flujo de Estados

### PRs

```
borrador → en-progreso → pendiente-revisión → aprobado → mergeado
                            ↓
                         rechazado → en-progreso (loop)
```

| Estado | Quién lo cambia | Descripción |
|---|---|---|
| `borrador` | Autor | PR creada, aún en desarrollo |
| `en-progreso` | Autor | Trabajo activo (después de rechazo o al empezar) |
| `pendiente-revisión` | Autor | PR lista para review |
| `rechazado` | Sergio | Review rechazada (requiere motivo) |
| `aprobado` | Sergio | Review aprobada, lista para merge |
| `mergeado` | Sergio | Mergeada a staging/main |

### Issues

```
abierto → en-progreso → pendiente-revisión → cerrado
                            ↓
                         rechazado → en-progreso (loop)
```

| Estado | Quién lo cambia | Descripción |
|---|---|---|
| `abierto` | Cualquiera | Issue nuevo |
| `en-progreso` | Asignado | Alguien está trabajando |
| `pendiente-revisión` | Asignado | Fix listo para review |
| `rechazado` | Sergio | No se implementa (requiere motivo) |
| `cerrado` | Sergio | Resuelto o descartado |

---

## Reglas de Transición

### Rechazo → En progreso

Cuando Sergio rechaza una PR:
1. Estado queda en `rechazado` (con motivo visible)
2. El autor retoma el trabajo
3. **El autor** cambia a `en-progreso` cuando empieza a corregir
4. Cuando termina, libera a `pendiente-revisión`

**¿Por qué manual?** Permite que pase tiempo, deja claro quién trabaja, el autor confirma que va a atender el feedback.

### Aprobación → Merge

1. Sergio aprueba → estado `aprobado`
2. **Solo Sergio** puede hacer merge → `mergeado`
3. Nadie más mergea sin su aprobación explícita

---

## Registro Automático en GitHub

Cada cambio de estado genera un **comentario** en la PR/issue:

```
[ESTADO] usuario @ YYYY-MM-DD HH:MM — motivo: "..."
```

### Tabla de Historial (al inicio del body)

Al inicio de cada PR/issue se muestra una tabla con el histórico completo:

```markdown
## Historial de Estados

| Fecha | Estado | Actor | Detalle |
|---|---|---|---|
| 2026-06-25 10:15 | mergeado | Sergio | Merge a staging |
| 2026-06-25 09:00 | aprobado | Sergio | Aprobado para merge |
| 2026-06-24 14:30 | pendiente-revisión | ardelperal | Breakpoint ajustado |
| 2026-06-23 11:00 | en-progreso | ardelperal | Ajustando breakpoint |
| 2026-06-23 07:29 | rechazado | Sergio | Motivo: "Breakpoint a 1050px" |
| 2026-06-20 09:07 | pendiente-revisión | ardelperal | Fix aplicado |
| 2026-06-17 10:00 | en-progreso | ardelperal | Retomando fix |
| 2026-06-16 12:52 | rechazado | Sergio | Motivo: "Botón gigante" |
| 2026-06-15 16:00 | pendiente-revisión | ardelperal | PR lista para review |
| 2026-06-12 09:15 | en-progreso | ardelperal | Desarrollo activo |
| 2026-06-11 14:30 | borrador | ardelperal | PR #129 creada |
```

**Reglas de la tabla:**
- Ordenada de más reciente a más antiguo
- Se actualiza automáticamente con cada cambio de estado
- Se inserta al inicio del body con `---` separador

### Índice de PR (después del historial)

Después de la tabla de historial, se inserta un índice compacto con la información esencial en apartados independientes:

```markdown
## 📋 Historial de Estados

| Fecha | Estado | Actor | Detalle |
|---|---|---|---|
| 2026-06-25 10:15 | ![_](https://img.shields.io/badge/mergeado-0E8A16) | Sergio | Merge a staging |
| 2026-06-23 07:29 | ![_](https://img.shields.io/badge/rechazado-d73a4a) | Sergio | [Ver motivo](#) |
| 2026-06-11 14:30 | ![_](https://img.shields.io/badge/borrador-0075ca) | ardelperal | PR #129 creada |

---

## 🔗 Issue Asociado

[#121](https://github.com/DysTelefonica/cadete/issues/121) - Colapsar navegación a hamburguesa

---

## 🌿 Rama de GitHub Asociada

`bugfix/121-responsive-hamburger`

---

## 🏷️ Estado Actual

![_](https://img.shields.io/badge/pendiente--revisi%C3%B3n-ebad4b)

---

## 📝 Cambios

- Implementar menú hamburguesa para viewports estrechos
- Ajustar dropdowns al viewport
- Agregar tests E2E para regresión

---

## 📄 Resumen
(Descripción detallada de la PR)
```

**Reglas del historial:**
- Para rechazos: `[Ver motivo](https://github.com/DysTelefonica/cadete/pull/NUM#issuecomment-ID)`
- Para otros estados: descripción breve del cambio
- Fechas ordenadas de más reciente a más antiguo
- Colores con badges de shields.io

**Colores de badges:**
- `borrador`: azul (#0075ca)
- `en-progreso`: amarillo (#FBCA04)
- `pendiente-revisión`: amarillo (#ebad4b)
- `rechazado`: rojo (#d73a4a)
- `aprobado`: verde (#0E8A16)
- `mergeado`: azul (#0075ca)
- `abierto`: azul oscuro (#236682)

**Iconos en títulos:**
- 📋 Historial de Estados
- 🔗 Issue Asociado
- 🌿 Rama de GitHub Asociada
- 🏷️ Estado Actual
- 📝 Cambios
- 📄 Resumen

### Ejemplos

```
[BORRADOR] ardelperal @ 2026-06-11 14:30
[EN-PROGRESO] ardelperal @ 2026-06-12 09:15
[PENDIENTE-REVISIÓN] ardelperal @ 2026-06-15 16:00
[RECHAZADO] Sergio @ 2026-06-16 12:52 — Motivo: "Botón gigante que no hace nada"
[EN-PROGRESO] ardelperal @ 2026-06-17 10:00 — Retomando fix
[PENDIENTE-REVISIÓN] ardelperal @ 2026-06-20 09:07
[APROBADO] Sergio @ 2026-06-25 09:00
[MERGEADO] Sergio @ 2026-06-25 10:15
```

---

## Comandos para Cambiar Estado

### Crear PR en estado borrador

```bash
gh pr create --title "fix(scope): descripción" --body "..." --draft
```

### Liberar PR para revisión

```bash
# Cambiar a pendiente-revisión
gh pr ready <number>

# Registrar en comentario
gh pr comment <number> --body "[PENDIENTE-REVISIÓN] $(git config user.name) @ $(date '+%Y-%m-%d %H:%M')"
```

### Rechazar PR (Solo Sergio)

```bash
# Cambiar etiqueta
gh pr edit <number> --add-label "rechazado" --remove-label "pendiente-revisión"

# Registrar rechazo con motivo
gh pr comment <number> --body "[RECHAZADO] Sergio @ $(date '+%Y-%m-%d %H:%M') — Motivo: \"$MOTIVO\""
```

### Aprobar PR (Solo Sergio)

```bash
# Cambiar etiqueta
gh pr edit <number> --add-label "aprobado" --remove-label "pendiente-revisión"

# Registrar aprobación
gh pr comment <number> --body "[APROBADO] Sergio @ $(date '+%Y-%m-%d %H:%M')"
```

### Mergear PR (Solo Sergio)

```bash
# Merge
gh pr merge <number> --squash

# Registrar merge
gh pr comment <number> --body "[MERGEADO] Sergio @ $(date '+%Y-%m-%d %H:%M')"
```

### Retomar PR rechazada (Autor)

```bash
# Cambiar a en-progreso
gh pr edit <number> --add-label "type:bug" --remove-label "rechazado"

# Registrar retoma
gh pr comment <number> --body "[EN-PROGRESO] $(git config user.name) @ $(date '+%Y-%m-%d %H:%M') — Retomando fix"
```

---

## Etiquetas de Estado (17 total)

### Estados (6)
| Etiqueta | Estado | Color |
|---|---|---|
| `borrador` | PR en desarrollo | `d4c5f9` |
| `en-progreso` | Trabajo activo | `FBCA04` |
| `pendiente-revisión` | Lista para review | `BFD4F2` |
| `rechazado` | Review rechazada | `d73a4a` |
| `aprobado` | Aprobada para merge | `0E8A16` |
| `mergeado` | Mergeada | `ffffff` |

### Tipo (4)
- `type:bug` — Corrección de bug
- `type:feature` — Nueva funcionalidad
- `type:docs` — Solo documentación
- `type:mantenimiento` — CI/infra/proceso

### Prioridad (3)
- `prioridad:alta` — Urgente o crítico
- `prioridad:media` — Importante, no bloquea
- `prioridad:baja` — Nice to have

### Workflow (4)
- `auto-aprobado` — No requiere review de Sergio
- `notificar-sergio` — Informar a Sergio (no requiere aprobación)
- `preparar-entorno` — CI/compose/dumps
- `salud-código` — Deuda técnica / null safety

---

## Roles y Responsabilidades

### Autor de la PR
- Crea PR en `borrador`
- Cambia a `en-progreso` cuando empieza
- Libera a `pendiente-revisión` cuando termina
- Si rechazada: retoma y cambia a `en-progreso`
- **Nunca** aprueba o mergea su propia PR

### Sergio (Reviewer)
- Revisa PRs en `pendiente-revisión`
- Aprueba → `aprobado` (con comentario)
- Rechaza → `rechazado` (con motivo obligatorio)
- Mergea → `mergeado` (solo después de aprobación)

### Equipo
- Pueden comentar en PRs
- Pueden crear issues
- No pueden cambiar estados sin autorización

---

## Ejemplo Completo: PR #129

```
2026-06-11 14:30  [BORRADOR] ardelperal
                  PR creada como draft

2026-06-12 09:15  [EN-PROGRESO] ardelperal
                  Desarrollo activo

2026-06-15 16:00  [PENDIENTE-REVISIÓN] ardelperal
                  PR lista para review

2026-06-16 12:52  [RECHAZADO] Sergio
                  Motivo: "Aparece botón gigante que no hace nada"

2026-06-17 10:00  [EN-PROGRESO] ardelperal
                  Retomando fix

2026-06-20 09:07  [PENDIENTE-REVISIÓN] ardelperal
                  Fix aplicado

2026-06-23 07:29  [RECHAZADO] Sergio
                  Motivo: "Solucionado parcialmente. Breakpoint a 1050px"

2026-06-23 11:00  [EN-PROGRESO] ardelperal
                  Ajustando breakpoint

2026-06-24 14:30  [PENDIENTE-REVISIÓN] ardelperal
                  Breakpoint ajustado

2026-06-25 09:00  [APROBADO] Sergio
                  Aprobado para merge

2026-06-25 10:15  [MERGEADO] Sergio
                  Merge a staging
```

---

## Formato de Issue

Cada issue debe seguir esta estructura:

```markdown
## 📋 Historial de Estados

| Fecha | Estado | Actor | Detalle |
|---|---|---|---|
| 2026-06-23 | ![_](https://img.shields.io/badge/rechazado-d73a4a) | Sergio | [Ver motivo](#) |
| 2026-06-11 | ![_](https://img.shields.io/badge/abierto-236682) | ardelperal | Issue #121 creado |

---

## 🔗 PRs Derivadas

| PR | Estado | Autor | Título |
|---|---|---|---|
| [#129](https://github.com/DysTelefonica/cadete/pull/129) | ![_](https://img.shields.io/badge/en--progreso-FBCA04) | ardelperal | Collapse navigation to hamburger |

---

## 📝 Contexto

(Descripción del problema y su origen)

---

## ✅ Listado de Acciones

### Completadas
- [x] Acción 1
- [x] Acción 2

### Pendientes
- [ ] Acción 3
- [ ] Acción 4

### Bloqueadas
- (ninguna o descripción)

---

## 📊 Métricas

- **Fecha creación:** YYYY-MM-DD
- **Días abierta:** X
- **Rechazos:** X
- **PRs derivadas:** X
- **Responsable:** usuario
```

**Reglas del historial de issues:**
- Mismos badges que PRs
- Links a comentarios de rechazo
- PRs derivadas con estado y links
- Métricas calculadas automáticamente

---

## Commands

```bash
# === PR: Crear en borrador ===
gh pr create --title "fix(scope): descripción" --body "..." --draft

# === PR: Liberar para revisión ===
gh pr ready <number>
gh pr comment <number> --body "[PENDIENTE-REVISIÓN] $(git config user.name) @ $(date '+%Y-%m-%d %H:%M')"

# === PR: Rechazar (Solo Sergio) ===
gh pr edit <number> --add-label "rechazado" --remove-label "pendiente-revisión"
gh pr comment <number> --body "[RECHAZADO] Sergio @ $(date '+%Y-%m-%d %H:%M') — Motivo: \"$MOTIVO\""

# === PR: Aprobar (Solo Sergio) ===
gh pr edit <number> --add-label "aprobado" --remove-label "pendiente-revisión"
gh pr comment <number> --body "[APROBADO] Sergio @ $(date '+%Y-%m-%d %H:%M')"

# === PR: Mergear (Solo Sergio) ===
gh pr merge <number> --squash
gh pr comment <number> --body "[MERGEADO] Sergio @ $(date '+%Y-%m-%d %H:%M')"

# === PR: Retomar rechazada (Autor) ===
gh pr edit <number> --add-label "en-progreso" --remove-label "rechazado"
gh pr comment <number> --body "[EN-PROGRESO] $(git config user.name) @ $(date '+%Y-%m-%d %H:%M') — Retomando fix"

# === Issue: Cambiar estado ===
gh issue edit <number> --add-label "en-progreso" --remove-label "abierto"
gh issue comment <number> --body "[EN-PROGRESO] $(git config user.name) @ $(date '+%Y-%m-%d %H:%M')"
```
