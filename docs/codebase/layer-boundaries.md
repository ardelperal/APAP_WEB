[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Layer boundaries

Esta página posee las reglas §1 a §7 de AGENTS verbatim: los límites entre routes, services y queries, las dependencias que poseen recursos, el ciclo de vida de `Settings`, los duplicados prohibidos y las reglas de HTTP. La regla §33 (arquitectura hexagonal) las outrank para slices convertidos; esta página cubre el layout `routes.py / service.py / queries.py` aún presente en `app/modules/**`.

## Regla 1 — Los límites entre capas son absolutos

Las routes manejan solo HTTP: parsing de formularios, guards de auth, redirects, renderizado HTML. Los services manejan todo el acceso a datos: SQL, validación, lógica de dominio. Nunca llame `client.execute_sql(...)` desde una route. Si el método de service aún no existe, créelo primero — no salte la capa como medida temporal.

En un slice convertido el mismo límite se sostiene con otros nombres: la route delega a un **use case** en `application/`, que alcanza los datos por un **port**. Ver [architecture.md](architecture.md) §33.3.

**Incorrecto** — SQL en route

```python
@router.post("/{id}/delete")
def delete_view(id: str, client = Depends(...)):
    client.execute_sql("UPDATE items SET activo = false WHERE id = $1", [id])
```

**Correcto** — la route delega al service

```python
@router.post("/{id}/delete")
def delete_view(id: str, client = Depends(...)):
    service.deactivate_item(client, id)
```

## Regla 2 — Las dependencias que poseen recursos deben usar yield

Cualquier dependencia que cree un objeto con método `.close()` debe usar `yield` para garantizar la limpieza — incluso ante excepciones.

**Incorrecto** — recurso filtrado en cada request

```python
def get_client() -> InsForgeClient:
    return InsForgeClient(url, key)
```

**Correcto** — cerrado tras cada request

```python
def get_client():
    client = InsForgeClient(url, key)
    try:
        yield client
    finally:
        client.close()
```

## Regla 3 — La configuración se parsea una sola vez, no por request

`Settings()` lee variables de entorno. Debe llamarse una vez al arranque, no en cada request. Cachee siempre.

**Incorrecto**

```python
def get_client():
    settings = get_settings()   # parses .env on every call
    return InsForgeClient(settings.url, settings.key)
```

**Correcto**

```python
@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

## Regla 4 — Una sola fuente de verdad por concepto de dominio

Nunca defina los mismos valores dos veces. Si tiene un StrEnum para un tipo de dominio, derive cualquier set o lista de él — no duplique.

**Incorrecto** — los mismos valores en dos sitios, divergirán

```python
VALID_TYPES = frozenset({"intake", "acogida", "salud"})
class TipoRol(StrEnum):
    INTAKE = "intake"
    ACOGIDA = "acogida"
    SALUD = "salud"
```

**Correcto** — una sola fuente

```python
class TipoRol(StrEnum):
    INTAKE = "intake"
    ACOGIDA = "acogida"
    SALUD = "salud"

VALID_TYPES = frozenset(r.value for r in TipoRol)
```

## Regla 5 — La validación vive en el service, no en las routes

Las reglas de negocio (campos requeridos, pertenencia a enums, restricciones de dominio) pertenecen a la capa de service. Las routes traducen el `ValueError` del service a una respuesta HTTP — no re-implementan las reglas.

En un slice convertido, los invariantes viven en `domain/` y los enforza el use case en `application/`; la route sigue traduciendo solo el error (ver [architecture.md](architecture.md) §33).

**Incorrecto** — validación duplicada en route

```python
def update_view(...):
    if not form_data.get("name"):
        return render_form(error="name required")   # duplicates service logic
```

**Correcto** — el service posee la validación, la route traduce la excepción

```python
def update_view(...):
    try:
        service.update_item(client, form_data)
    except ValueError as exc:
        return render_form(error=str(exc))
```

## Regla 6 — Los defaults de seguridad deniegan, no permiten

Cuando lea un flag de sesión o payload, use como default el valor más restrictivo. Un campo ausente debe tratarse como la opción más segura.

**Incorrecto** — flag ausente concede acceso

```python
if not payload.get("is_authorized", True):
    redirect("/unauthorized")
```

**Correcto** — flag ausente deniega acceso

```python
if not payload.get("is_authorized", False):
    redirect("/unauthorized")
```

## Regla 7 — Los redirects no son excepciones

Use `RedirectResponse` para redirects de control de flujo. Reserve `HTTPException` para condiciones HTTP reales (4xx, 5xx). Mezclarlas confunde el tracking de errores, el middleware y Sentry.

**Incorrecto** — abusar de `HTTPException` para redirect

```python
raise HTTPException(status_code=302, headers={"location": "/login"})
```

**Correcto**

```python
return RedirectResponse(url="/login", status_code=302)
```

## Checklist de envío antes de mergear una route o service

- [ ] ¿La route llama a `client.execute_sql(...)` directamente? → Mover al service.
- [ ] ¿Alguna dependencia crea un recurso cerrable? → Use yield + finally.
- [ ] ¿El código llama a `get_settings()` más de una vez en el mismo request? → Cachee.
- [ ] ¿La misma lista de valores de dominio está definida dos veces? → Derive una de la otra.
- [ ] ¿Algún check de auth defaultea a `True`? → Cambie a `False`.
- [ ] ¿Algún redirect usa `HTTPException`? → Use `RedirectResponse`.

## Contributor checklist

- [ ] Cada nueva route delega al service (o al use case en slice hexagonal) — nunca SQL directo.
- [ ] Cada dependencia cerrable usa `yield` con `try/finally`.
- [ ] `Settings()` se cachea con `@functools.lru_cache` o equivalente; no se re-parsea por request.
- [ ] Los enums de dominio son la única fuente de verdad para sets/listas derivados.
- [ ] Defaults de flags de auth son `False`, nunca `True`.
- [ ] Redirects usan `RedirectResponse`; `HTTPException` queda para 4xx/5xx reales.

## Navigation

Previous: [Codebase Guide](../CODEBASE-GUIDE.md) | Next: [Quality gates](quality-gates.md)
