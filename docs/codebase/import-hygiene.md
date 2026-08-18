[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Import hygiene

Esta página posee las reglas §25, §26 y §27 de AGENTS verbatim: la prohibición de helpers duplicados cross-módulo, el marcador obligatorio para `import` locales que esquivan ciclos, y el uso exclusivo de la API pública del paquete destino en imports cross-módulo.

## Regla 25 — Sin helpers cross-módulo duplicados

La regla §4 dice una sola fuente de verdad por concepto de dominio para *valores* (enums, listas). Para los nombres de helper vigilados explícitamente por el Detector 10, aplique el mismo principio: no los copie-pegue entre módulos. La revisión de arquitectura del 2026-07-20 encontró `_opt()` copiado casi-idéntico en cinco `routes.py` (`app/modules/{animals,entradas,foster,materiales}/routes.py` + `materiales/acogida_routes.py` — y, una vez corrió la watch-list completa, en varios más) y `_required_text`/`_optional_text` reimplementados a lo largo de ocho `service.py`. Cada copia decía en su docstring "mirrors X" — la duplicación se *notó* y se dejó igual, porque no había módulo compartido al que importar y ningún gate que detuviera el copia-pega. El issue #227 rastrea la consolidación de estos helpers en un módulo compartido; esta regla previene que esos helpers vigilados específicamente vuelvan a propagarse una vez que #227 se arregle.

**Incorrecto** — notar la duplicación y copia-pegar igual

```python
# app/modules/materiales/routes.py
def _opt(value: str | None) -> str | None:
    """Mirrors the ``_opt`` precedent in ``app/modules/foster/routes.py``."""
    if value is None:
        return None
    return value.strip() or None
```

**Correcto** — un helper compartido, cada módulo lo importa

```python
# app/core/form_helpers.py
def opt(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None

# app/modules/materiales/routes.py
from app.core.form_helpers import opt as _opt
```

**Aplicación**: un **guard de regresión por watch-list**, no un detector general de código duplicado — `scripts/check_rules.py` Detector 10 (`duplicate_helper_definition`) inspecciona solo los nombres listados explícitamente en `WATCHED_DUPLICATE_HELPERS` (inicialmente `_opt`, `_required_text` y `_optional_text`). Para cada nombre vigilado, las definiciones ya registradas en el ratchet shrink-only `BASELINE_DUPLICATE_HELPERS` se toleran; cualquier definición en un archivo adicional falla. Un nombre vigilado sin baseline falla cuando se define en más de un archivo. Las llamadas, imports, helpers con nombre distinto y duplicados semánticos quedan fuera del alcance de este detector. Tests: `tests/test_check_rules.py` (sección del Detector 10).

## Regla 26 — Justifique o elimine los workarounds de lazy-import por ciclos

Un `import` local dentro del cuerpo de una función o método bajo `app/` es una escotilla de escape deliberada para ciclos de imports — nunca debe ser silenciosa. La revisión del 2026-07-20 encontró exactamente dos de esos imports (la propiedad `writer_rols` de `app/core/config.py` que importa `Rol` desde `auth.py`; `app/core/auth_dependencies.py` que importa `get_user_by_email` desde `auth.py` dentro de una función), rastreados en el issue #226. Ambos esquivan un ciclo real de carga de módulos, pero ninguno lo decía de manera greppable y consistente. Un import local sin explicación es o un ciclo sin resolver (merece arreglarse en el origen) o trivialmente seguro de izar al top — en cualquier caso, la siguiente persona que lo lea merece una razón de una línea en lugar de tener que reverso-ingeniar el grafo de imports.

**Incorrecto** — import local sin explicar

```python
def get_settings_rol(self):
    from app.core.auth import Rol
    return Rol
```

**Correcto** — el comentario dice por qué no puede ser un import al top

```python
def get_settings_rol(self):
    # lazy-import: avoids circular import with app.core.auth (auth.py
    # imports Settings at module load time).
    from app.core.auth import Rol
    return Rol
```

**Aplicación**: `scripts/check_rules.py` Detector 11 (`unjustified_lazy_import`) marca cualquier nodo `Import`/`ImportFrom` cuyo scope envolvente más cercano sea una función o método (no a nivel de módulo) bajo `app/`, salvo que su propia línea de código o la línea inmediatamente anterior contenga la subcadena `lazy-import:`. Ambas instancias conocidas (`app/core/config.py`, `app/core/auth_dependencies.py`) llevan ahora el marcador. Tests: `tests/test_check_rules.py` (sección del Detector 11).

## Regla 27 — Los imports cross-módulo van solo por la API pública del módulo destino

La auditoría de mapa de dependencias del 2026-07-20 confirmó que este proyecto es por lo demás un DAG limpio con casi cero acoplamiento entre módulos — la mayoría de los módulos de dominio bajo `app/modules/` no importa nada entre sí. Surgieron dos excepciones: `app/modules/foster/assignment.py` importaba `app.modules.animals.service` directamente (saltándose `animals/__init__.py`, que no expone API pública — issue #231), y `app/modules/acogidas/routes.py` hacía el shorthand-submodule import equivalente a `foster.assignment` en lugar de usar el nombre `assignment_service` que `foster/__init__.py` ya exporta públicamente (arreglado directamente en el PR que añadió esta regla). Esta regla existe para mantener el DAG limpio a medida que el proyecto crezca a más módulos.

Desde `app/modules/<A>/`, un import de `app/modules/<B>/` (A != B) DEBE (a) importar desde el paquete `app.modules.<B>` (su superficie pública en `__init__.py`), nunca una ruta de submódulo como `app.modules.<B>.service` — incluido el shorthand `from app.modules.<B> import service`, que alcanza el mismo submódulo — y (b) nunca importar un nombre que empiece por `_`, sin importar la fuente.

**Incorrecto** — alcanzar directamente un submódulo de un módulo hermano

```python
# app/modules/foster/assignment.py
from app.modules.animals import service as animals_service
```

**Correcto** — importar desde la API pública declarada del módulo destino

```python
# app/modules/animals/__init__.py
from app.modules.animals.service import get_animal_by_id

# app/modules/foster/assignment.py
from app.modules.animals import get_animal_by_id
```

**Aplicación**: `scripts/check_rules.py` Detector 12 escanea cada `ImportFrom` bajo `app/modules/**/*.py` cuyo path de módulo empieza por `app.modules.` y apunta a un módulo *distinto* del propio archivo importador. Marca `cross_module_submodule_import` cuando el import alcanza más allá de `app.modules.<name>` (literalmente, o vía el shorthand `from app.modules.<name> import <submodule>`, detectado comprobando si el nombre importado matchea un archivo/paquete real bajo el módulo destino), y `cross_module_private_import` cuando cualquier nombre importado empieza por `_`. La única instancia aún abierta (issue #231 — `animals/__init__.py` necesita una API pública real diseñada antes de que el import pueda arreglarse, fuera de alcance para un cambio de docs/tooling) queda grandfathered en una allowlist shrink-only `BASELINE_CROSS_MODULE_IMPORTS`; nunca pueden añadirse entradas nuevas. La desviación de "helper privado reusado por archivo hermano" del mismo módulo (por ejemplo, issue #232, `entradas/batch_service.py` importando los helpers prefijo-underscore de `entradas/service.py`) es un patrón real pero *distinto* — mismo directorio, no cross-módulo — y queda intencionalmente fuera del alcance de este detector; se queda en revisión de PR hasta que una variante mismo-módulo valga el riesgo de falso positivo de marcar helper sharing intra-paquete legítimo. Tests: `tests/test_check_rules.py` (sección del Detector 12).

## Core invariants

- **Una fuente por nombre vigilado**: cada nombre en `WATCHED_DUPLICATE_HELPERS` vive en un solo archivo (o en `BASELINE_DUPLICATE_HELPERS`).
- **Marcador obligatorio en lazy-imports**: cualquier `Import`/`ImportFrom` dentro de función lleva `# lazy-import:` en su línea o en la anterior.
- **API pública como destino cross-módulo**: nunca `app.modules.<X>.service` desde `app/modules/<otro>/`, nunca nombres con `_` inicial.
- **Shrink-only ratchet**: `BASELINE_DUPLICATE_HELPERS` y `BASELINE_CROSS_MODULE_IMPORTS` solo decrecen.

## Contributor checklist

- [ ] Cada nuevo helper cuyo nombre entra en la watch-list se importa desde un módulo compartido.
- [ ] Cada lazy-import nuevo bajo `app/` lleva el marcador `# lazy-import:` con justificación.
- [ ] Cada import cross-módulo desde `app/modules/<A>/` apunta a `app.modules.<B>`, no a un submódulo.
- [ ] Ningún nombre importado empieza por `_`, sin importar el archivo fuente.

## Navigation

Previous: [Module size budgets](module-size-budgets.md) | Next: [Code quality rules](code-quality-rules.md)
