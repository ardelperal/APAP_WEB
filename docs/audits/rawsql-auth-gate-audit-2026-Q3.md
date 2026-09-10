[← Volver a la guía del código](../CODEBASE-GUIDE.md)

# Auditoría del control de acceso a raw SQL — 2026 Q3

## Alcance

La auditoría revisa el endpoint `POST /api/database/advance/rawsql` de la
aplicación LocalBackend y el cierre del issue #680.

| Área | Evidencia |
|---|---|
| Arranque | `app/core/local_backend/app.py` |
| Handler | `app/core/local_backend/rawsql.py` |
| Configuración | `app/core/config.py` |
| Pruebas | `tests/test_rawsql_auth.py`, `tests/integration/test_local_backend.py` |
| Operación | `docs/runbooks/rawsql-auth-token.md` |

`app.main` queda fuera del control del token porque no monta este router. Exigir
el secreto en su `_validate_secrets` rompería el proceso web sin proteger una
superficie accesible desde él.

## Modelo de amenaza

El endpoint acepta SQL arbitrario y usa las credenciales PostgreSQL de
LocalBackend. Si se expone sin autenticación, permite leer o modificar cualquier
dato accesible para ese rol de base de datos.

## Controles verificados

1. El lifespan de LocalBackend rechaza un token ausente o inferior a 32
   caracteres antes de servir tráfico.
2. El token validado se almacena en `app.state`; el handler no consulta una
   configuración global por petición.
3. El handler exige el esquema `Bearer` y una coincidencia exacta mediante
   `hmac.compare_digest`.
4. Todos los fallos de autenticación devuelven `401`, `WWW-Authenticate: Bearer`
   y el mismo detalle genérico.
5. La autenticación ocurre antes de acceder al executor.
6. Los errores y respuestas no incluyen el token ni explican el estado interno
   de configuración.

## Pruebas

| Tipo | Evidencia | Riesgo cubierto |
|---|---|---|
| Unit | `_require_rawsql_token` | Esquema, coincidencia exacta y default-deny |
| Route integration in-process | Peticiones ASGI con executor espía | Rechazo antes del side effect y contrato `401` |
| Application startup | Lifespan de `create_app` | Token ausente o débil impide arrancar LocalBackend |
| Integration con PostgreSQL | `test_local_backend.py` | El contrato autorizado conserva el round-trip real |
| Verificación de fallback | Token efímero compartido por los subprocesos | El LocalBackend de CI arranca sin reutilizar secretos persistentes |

No procede una prueba E2E de interfaz: esta superficie no tiene UI. La prueba con
PostgreSQL sigue en la suite de integración dedicada.

## Hallazgos

### Resuelto — endpoint sin autenticación

El handler anterior ejecutaba el payload sin comprobar identidad. Ahora requiere
un bearer token validado antes de cualquier llamada al executor.

### Resuelto — validación en el proceso equivocado

La primera implementación añadió `APAP_RAWSQL_AUTH_TOKEN` a
`app.core.config._validate_secrets`. Esa función pertenece al arranque de
`app.main`, que no monta raw SQL. La validación se trasladó al lifespan de
LocalBackend para mantener el límite de responsabilidad y evitar un secreto
inútil en el proceso web.

### Resuelto — respuestas diagnósticas

La primera implementación distinguía token ausente, endpoint deshabilitado y
token incorrecto. El handler devuelve ahora un único error genérico para no
revelar detalles operativos.

## Veredicto

**Aprobado para el alcance auditado.** LocalBackend falla cerrado en arranque y
en cada petición. El proceso web conserva su contrato de configuración porque no
expone el endpoint.

Riesgo residual: quien posea el token obtiene toda la capacidad del endpoint.
Debe almacenarse como secreto de alta sensibilidad, limitarse la exposición de
red y rotarse ante cualquier sospecha de fuga.
