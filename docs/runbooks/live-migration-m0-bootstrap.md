[← Back to README](../../README.md)

# live-migration-m0-bootstrap.md

Este runbook es el procedimiento del operador para preparar la infraestructura mínima previa a la primera migración de datos en vivo en la cadena `live-data-migration-sandbox`. Aplica al PR2/M0.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Lista de comprobación previa | Verificaciones de credenciales y ámbito del trabajo |
| Pasos de despliegue | Checkpoint de sólo lectura y creación privada del bucket |
| Verificación | Estado `isPublic=false` y pruebas de shadow state |
| Reversión | Alternativas no destructivas frente a las destructivas de último recurso |

## Cuándo abrir este runbook

Abra este runbook antes de la primera ejecución de migración de datos en vivo en la cadena `live-data-migration-sandbox`. Ábralo también tras cualquier reversión que haya eliminado `web_only_feature_shadow` o el bucket `apap-photos`.

## Lista de comprobación previa

- Las pruebas de código del PR2 pasan en verde; no ejecute este runbook contra InsForge como parte del pytest ordinario.
- `APAP_INSFORGE_URL` apunta al backend APAP previsto.
- `APAP_INSFORGE_SERVICE_KEY` está disponible sólo en el shell del operador, nunca en el repositorio.
- No se está ejecutando una importación real de datos en esta unidad de trabajo; este paso sólo prepara y verifica infraestructura.

## Pasos de despliegue

1. **Checkpoint de sólo lectura:**

    ```bash
    python -m migration ensure-bucket apap-photos --check-only
    ```

    Salida esperada del estado privado:

    ```text
    bucket=apap-photos status=exists isPublic=false
    ```

2. **Si el bucket no existe y el operador aprueba la mutación de infraestructura**, créelo como privado:

    ```bash
    python -m migration ensure-bucket apap-photos
    ```

    Salida esperada:

    ```text
    bucket=apap-photos status=created isPublic=false
    ```

3. **No ejecute una aplicación real en esta unidad de trabajo PR2.** La siguiente ejecución no-de-check-only de `python -m migration apply …` se encargará de asegurar `web_only_feature_shadow` antes de adquirir el lock de migración y antes de leer filas legadas. Si un operador elige pre-crear la tabla por separado, use la DDL en `migration/shadow_state.py`, registre el checkpoint y conserve la reversión siguiente disponible.

## Verificación

- La salida del comando debe incluir `isPublic=false`.
- Si el comando devuelve `bucket_public_violation`, deténgase. No aplique datos. Recree el bucket como privado mediante la herramienta de infraestructura de InsForge y reejecute el checkpoint de sólo lectura.
- Si el comando devuelve `bucket_visibility_unknown`, deténgase. Use la herramienta MCP `list-buckets` de InsForge para verificar la visibilidad antes de continuar.
- `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -v` debe pasar localmente sin acceso al backend real.

## Reversión

> **Las acciones destructivas en esta sección son de último recurso.** Descartan artefactos duraderos de los que dependen el operador y el rastro de auditoría. no las use como camino de reversión por defecto. Prefiera las alternativas no destructivas en primer lugar; si un paso destructivo es inevitable, los precondiciones siguientes deben cumplirse y registrarse antes de que el operador ejecute el comando.

### Alternativas no destructivas (preferidas)

- **Desactivación de shadow state en lugar de `DROP TABLE`:** mantenga la tabla `web_only_feature_shadow` y el historial de divergencia/auditoría intactos. Detenga futuras ejecuciones de `apply` borrando `migration.lock_snapshot.json` (si existe) y usando los overrides de `APAP_MIGRATION_DIR` para apuntar la siguiente ejecución de `apply` a un destino no-op. La tabla continúa registrando el historial de auditoría para el lado legado. Esta es la reversión por defecto cuando la tabla contiene filas.
- **Cuarentena del bucket en lugar de `delete-bucket`:** mantenga los objetos del bucket en su sitio y evite nuevas subidas eliminando el permiso del rol de servicio de InsForge para el bucket. Las fotografías existentes permanecen disponibles para lecturas autenticadas; el rastro de auditoría permanece intacto.
- **Modo checkpoint-only del CLI** (`python -m migration ensure-bucket apap-photos --check-only`) es una herramienta no mutante del operador. Ejecútelo para verificar el estado sin escribir.

### Reversión destructiva (último recurso)

**`DROP TABLE web_only_feature_shadow`**

- **Efecto**: destructivo del historial de divergencia/auditoría para cada fila pendiente en `needs_review`. Una vez eliminadas las filas, el operador pierde la evidencia de hashes de origen/destino y el flujo de conciliación manual del que dependen PR5/PR6.
- **Precondiciones (deben cumplirse antes de que el operador ejecute el comando):**
    1. Una copia de seguridad verificada de la tabla (por ejemplo, `pg_dump --table web_only_feature_shadow`) se almacena fuera de la base de datos InsForge afectada y la ruta queda registrada en el ticket del operador.
    2. `SELECT COUNT(*) FROM web_only_feature_shadow WHERE reconciliation_status IN ('pending', 'needs_review')` devuelve `0`, O el operador ha registrado una aprobación explícita en el ticket explicando por qué la pérdida de filas resulta aceptable. <!-- alantyle-ignore:ALAN003 -->
    3. Ninguna migración en curso depende de la tabla (sin `migration.lock` activo; sin ejecuciones abiertas de `apply`/`reconcile`).
- **no use `TRUNCATE` como alternativa "más segura".** `TRUNCATE` no participa de la transacción de reversión; elimina permanentemente todas las filas sin registro por fila, que es exactamente lo que las precondiciones de copia verificada y prueba de vacío están diseñadas para impedir. Si se requiere un reinicio destructivo, el operador debe usar `DROP TABLE` junto con la copia verificada.

**`delete-bucket apap-photos`**

- **Efecto**: destructivo de cada fotografía cargada actualmente bajo el bucket, incluyendo los datos ya referenciados por `animales.nombrefoto` en la base de datos web. La ruta `GET /animales/{animal_id}/foto` recurrirá a bytes de placeholder para cada fila cuya clave de objeto desaparezca.
- **Precondiciones (deben cumplirse antes de que el operador ejecute el comando):**
    1. Una exportación verificada del contenido del bucket (descarga desde InsForge Storage o equivalente) se almacena fuera del despliegue InsForge afectado y la ruta queda registrada en el ticket del operador.
    2. `apap-photos` está vacío (recuento de objetos en `apap-photos` igual a 0) O el operador ha registrado una aprobación explícita en el ticket explicando por qué la pérdida de las fotografías resulta aceptable.
    3. Ninguna migración en curso depende del bucket (sin ejecuciones activas de `apply`/`reconcile` que referencien el bucket).
- **Nunca reemplace el bucket por un bucket público.** La invariante privada de PR2 (`isPublic=false`) es un contrato estricto de privacidad; reconstruir el bucket como público queda rechazado por la comprobación fail-closed del bootstrap.

### Reversión de código (sin efecto sobre los datos)

Revierta el commit de PR2. Esta operación elimina el checkpoint del CLI, el cableado del bootstrap del bucket y las pruebas, sin tocar porciones de migración no relacionadas ni estado vivo de InsForge.

## Documentos relacionados

- `migration/shadow_state.py` — DDL de `web_only_feature_shadow` y semillas.
- `migration/photo_migration.py` — flujo de subida de fotografías ejecutado por el pass de `animal`.
- `AGENTS.md` §18 — exclusión mutua web ↔ legacy y sincronización obligatoria.