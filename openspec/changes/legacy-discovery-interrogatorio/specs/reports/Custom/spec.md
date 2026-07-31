# Spec: REPORT-05 — Custom SQL Reports (issue #64, task 3.8)

## Context

Issue #64. Permiten a los operadores definir y ejecutar queries SQL guardadas
(arbitrarias) contra la base de datos. El legado almacenaba SQL en la DB y lo
ejecutaba directamente — esto es un riesgo de seguridad. El web app debe
implementar queries parametrizadas o un sandbox seguro.

## Current state on main@0ab533d

**No existe** este feature. El legacy tiene `TbInforme` con SQL arbitrario
almacenado y ejecutado sin sandbox.

**Riesgo conocido:** `docs/discovery/feature-04-documents-contracts-reports.md` §4.4:
> "The legacy system stores arbitrary SQL in the database and executes it directly.
> This is a significant security risk."

**GAP:** La arquitectura exacta del sandbox no está definida en los discovery docs.
Hay tres opciones listed: curated templates, query builder, o sandboxed execution.

## Required contract

### GAP: Security model not defined

> **[GAP: needs discovery before implementation]** No hay enough evidencia en los
> discovery docs para definir el modelo de seguridad de los custom reports.
> Opciones identificadas pero no decididas:
> 1. **Curated templates**: pre-defined report templates con inputs parametrizados
>    (el operador elige plantilla + llena parámetros, no SQL libre).
> 2. **Query builder visual**: constructor de queries que genera SQL seguro.
> 3. **Sandboxed execution**: SQL libre validado contra allow-list de tablas y
>    operaciones antes de ejecutar.
>
> Necesita decisión de producto antes de implementar.

### Si se elige curated templates

#### Tabla `reportes_guardados`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `nombre` | TEXT | Nombre del informe |
| `descripcion` | TEXT | Descripción |
| `template_key` | TEXT | Clave de la plantilla (e.g. "adopciones_por_mes") |
| `parametros` | JSONB | Valores de parámetros para esta ejecución |
| `creado_por` | TEXT | user_id |
| `creado_en` | TIMESTAMPTZ | Timestamp |

#### Endpoint

```
GET /reportes/plantillas                # lista plantillas disponibles
POST /reportes/ejecutar                 # ejecuta con parámetros
GET  /reportes/historial                # historial de ejecuciones del operador
```

#### Service function

```python
@dataclass
class ReportTemplate:
    key: str
    nombre: str
    descripcion: str
    sql_template: str  # e.g. "SELECT * FROM adopciones WHERE fecha_adopcion >= {{ fecha_desde }}"
    parametros: list[ReportParam]

def ejecutar_reporte(
    client: SqlExecutor,
    template_key: str,
    parametros: dict[str, Any]
) -> ReportResult:
    """
    Valida parámetros contra template.parametros,
    interpola en sql_template,
    ejecuta contra InsForge,
    retorna resultados.
    """
```

## Dependencies

- Ninguna dependencia fuerte — es standalone.

## Acceptance criteria

1. `GET /reportes/plantillas` lista plantillas con `nombre`, `descripcion`,
   `parametros` (sin SQL).
2. `POST /reportes/ejecutar` valida parámetros contra la template antes de ejecutar.
3. SQL injection en parámetros → 422 (parámetros solo se sustituyen en valores,
   no en columnas ni keywords SQL).
4. El resultado se puede exportar a CSV.
5. `GET /reportes/historial` lista las últimas 20 ejecuciones del operador.
6. Logs via `log_safe("report.ejecuted", template_key, row_count, ...)` con
   parámetros no sensibles.

## Out-of-scope

- Crear/editar plantillas (operadores no crean SQL — solo usan plantillas predefinidas).
- Scheduling de reports automáticos.
