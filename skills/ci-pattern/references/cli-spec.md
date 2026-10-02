# Especificación de la CLI `ci-pattern`

Adoptador/actualizador/verificador determinista del patrón de CI. Diseñada para
que una IA la invoque con una frase («actualizá el sistema de gobernanza»,
«adoptá el patrón en este repo», «verificá el cumplimiento») y ejecute sin
imaginar nada: cada comando lee datos estructurados y emite una salida terse,
agrupada y accionable.

- **Implementación:** `assets/bin/ci-pattern` (relativo a la raíz de la skill;
  canónica en `DysTelefonica/team-skills`, `~/personal-skills`, y resuelta igual
  en cualquier mirror). Python 3 stdlib exclusivamente — sin venv, sin dependencias
  de terceros, ejecutable con `python3` y desde CI.
- **Estado de esta wave:** entregados `params validate`, `verify`, `status`, el
  formato de manifiesto y su lectura/escritura. `adopt` y `update` son la wave
  siguiente; la extracción de plantillas desde el origen (`ardelperal/APAP_WEB`)
  sigue pendiente — este documento lo declara, no lo simula.

---

## §1 Comandos

| Comando | Estado | Qué hace |
|---|---|---|
| `ci-pattern params validate <file>` | **Entregado** | Valida un fichero de parámetros contra `assets/parameters.schema.json` (§5). |
| `ci-pattern verify <repo>` | **Entregado** | Comprobación de cumplimiento dirigida por el manifiesto (§4). |
| `ci-pattern status <repo>` | **Entregado** | Resumen de una línea por clase: manifiesto presente, ficheros OK/modificados/ausentes, gates cableados, bloques de slice. |
| `ci-pattern manifest show <repo>` | **Entregado** | Imprime el manifiesto leído (lectura; la escritura vive en la librería y la ejercitan los tests). |
| `ci-pattern adopt <repo>` | Wave siguiente | Copiará plantillas, sustituirá parámetros, escribirá el manifiesto y abrirá el PR de gobernanza. Hoy: mensaje claro + exit 4. |
| `ci-pattern update <repo>` | Wave siguiente | Re-sincronizará ficheros adoptados con la versión canónica, respetando el contrato de idempotencia (§6). Hoy: mensaje claro + exit 4. |

Flags globales: `--dry-run` (aceptado por `adopt`/`update`; sin efecto destructivo
en los comandos entregados, que ya son de solo lectura salvo la escritura del
manifiesto de `adopt`), `--json` (salida máquina en `verify`, `status` y
`manifest show`), `--slice-canonical <dir>` en `verify` para contrastar los
bloques de slice contra el catálogo canónico.

## §2 Códigos de salida

| Código | Significado |
|---|---|
| `0` | Limpio: sin hallazgos o validación correcta. |
| `1` | Hallazgos: la verificación encontró desviaciones o la validación rechazó el fichero. |
| `2` | Error de uso: comando o argumentos desconocidos. |
| `3` | Recurso ausente o ilegible: manifiesto o fichero de parámetros inexistente/corrupto. |
| `4` | Comando reservado a una wave futura (`adopt`, `update`). |

## §3 Formato del manifiesto (`.governance-manifest.json`)

Vive en la raíz del repo adoptante. Escrito por `adopt` (wave siguiente); la
librería ya implementa lectura y escritura y los tests ejercitan el round-trip.

```json
{
  "schema_version": 1,
  "adopted_at": "2026-10-02T12:00:00Z",
  "canonical_version": "0.4",
  "canonical_source": {
    "repo": "DysTelefonica/team-skills",
    "path": "personal/ardelperal/ci-pattern"
  },
  "parameters": {
    "P06_review_budget_lines": 400,
    "P10_label_approval": "status:approved"
  },
  "files": {
    "scripts/check_pr_size.py": "sha256:…",
    ".github/workflows/pr-size.yml": "sha256:…"
  },
  "slice_blocks": {
    "APAP_WEB": "sha256:…"
  }
}
```

- `schema_version`: `1`. Un manifiesto con otra versión se rechaza con exit 3.
- `canonical_source`: repo + ruta del catálogo canónico del que se adoptó.
- `parameters`: mapa `P<NN>_<snake_name>` → valor validado contra el esquema.
- `files`: ruta repo-relativa → `sha256:<hex>` del contenido adoptado.
- `slice_blocks`: nombre del bloque de slice (`<!-- personal-skills:slice:NAME @ … -->`
  en `AGENTS.md`) → `sha256:<hex>` del contenido entre marcadores (sin las líneas
  de marcador, saltos incluidos tal cual).

## §4 Contrato de `verify`

`verify <repo>` es de solo lectura y NUNCA escribe ni corrige. Comprobaciones,
agrupadas por clase en la salida:

1. **`manifest`** — existe, es JSON válido, `schema_version: 1`. Ausente: exit 3
   con la instrucción de ejecutar `adopt` (o de generarlo si se adoptó a mano).
2. **`files`** — cada ruta del manifiesto existe y su sha256 coincide. Divergencia:
   hallazgo `locally-modified` (el contenido del repo manda; el manifiesto se
   actualiza vía `update`, no a mano). Ausencia: hallazgo `missing`. La CLI jamás
   sobrescribe ni restaura ficheros.
3. **`gates`** — cada job de `P23_required_jobs` debe aparecer como job
   (`^\s*<job>:`) en algún fichero de `.github/workflows/*.yml`. Un job sin
   cablear es hallazgo `gate-not-wired` con el nombre y la clase de hallazgo.
4. **`slice_blocks`** — para cada nombre: el bloque existe en `AGENTS.md` y su
   hash coincide con el manifiesto (`locally-modified`, `missing` en su defecto).
   Con `--slice-canonical <dir>`, contrasta además contra `<dir>/<NAME>.md`
   (`stale-vs-canonical` cuando la canónica avanzó y el consumer no re-propagó —
   la fisura de drift que motivó esta wave). Sin ese flag, la salida lo declara
   como advertencia: la comparación canónica no se ejecutó.

Salida no-JSON: cabecera por clase y un hallazgo por línea
`<clase>: <detalle accionable>`. `--json`: `{"repo", "clean", "findings":
[{"class", "code", "detail"}], "canonical_comparison": "performed"|"skipped"}`.
Exit `0` limpio, `1` con hallazgos.

## §5 Parámetros y su validación

El contrato de datos es `assets/parameters.schema.json` (P01–P48); el fichero del
adoptante es `ci-pattern.yaml`. El parser acepta un subconjunto estricto de YAML:
mapeo de un nivel, listas en bloque (`- item`) o inline (`[a, b]`), mapas anidados
de un nivel, escalares (entero, flotante, booleano, cadena con o sin comillas) y
comentarios `#`. Tabulación, clave duplicada o indentación ambigua son error con
número de línea.

Cada entrada del esquema declara: `id`, `name`, `type`, `default`, `required`,
`consumed_by` (evidencia `fichero:línea` del origen) y restricciones del tipo
(`min`, `choices`, `pattern`, `value_type`). Tipos: `regex`, `string`, `label`,
`path`, `integer`, `float`, `boolean`, `list`, `map`, `enum`, `object`.

`params validate <file>` rechaza con exit 1 y un mensaje por error, siempre
nombrando el parámetro (id + name) y la forma esperada:

- **Clave desconocida** — «no está en el esquema; revise el nombre o elimínelo».
- **Faltante obligatorio** — «obligatorio, sin default seguro; establézcalo».
- **Tipo incorrecto** — «debe ser <type>, se recibió <valor de tipo X>».
- **Regex inválida** — el error de `re.compile` del parámetro.
- **Etiqueta mal formada** — debe ser `prefijo:valor` (p. ej. `status:approved`).
- **Ruta ilegal** — absoluta o con `..` (el manifiesto opera con rutas relativas).

Valida también los defaults declarados en el esquema: el propio esquema no puede
contener un valor que su validador rechazaría.

## §6 Contrato de idempotencia (vigente para `update`, wave siguiente)

Re-ejecutar la herramienta sobre un repo ya adoptado no altera bytes generados
ni duplica bloques. Cada fichero generado se registra por sha256 en el manifiesto;
`update` solo reescribe cuando el hash canónico cambió, y jamás toca un fichero
modificado localmente sin reportarlo como hallazgo `locally-modified`.

## §7 Lo que la CLI NUNCA hace

- Nunca ejecuta `git merge`, `git push`, ni publica nada.
- Nunca toca producción (ninguna llamada de red salvo la que el operador pase
  por argumento; `verify` es 100 % filesystem).
- Nunca borra ficheros que ella misma no escribió; jamás ejecuta `rm` ni
  equivalentes.
- Nunca sobrescribe un fichero modificado localmente sin reportarlo como
  hallazgo.
- Nunca decide el contenido de los parámetros: los lee, los valida y falla
  fuerte; los valores los elige el operador.

## §8 Frontera honesta (juicio humano/IA)

Estos puntos quedan fuera del determinismo, con procedimiento acotado:

- **Los valores de los parámetros** (qué presupuesto, qué etiquetas): el esquema
  valida la forma, no la intención. Decisión del operador.
- **Los conflictos de contenido** tras un `update` (fichero modificado en el
  destino y canónica avanzada): la CLI los reporta; la disposición es humana.
- **La disposición de los veredictos** de `verify`: limpio/no limpio es
  determinista, qué corregir y en qué orden es juicio del agente con la lista
  accionable en la mano.
- **La completitud de una spec, la causa raíz de un rojo, si una edición es
  material**: según `references/porting-guide.md` y el playbook del origen.

## §9 Receta de uso para una IA (flujo de 5 comandos)

Diseñada para que la salida de cada paso alimenta el siguiente, sin prosa
intermedia:

```bash
# 1. Estado actual del repo destino (¿hay manifiesto? ¿está limpio?)
ci-pattern status <repo>

# 2. Validar los parámetros del adoptante ANTES de escribir nada
ci-pattern params validate ci-pattern.yaml

# 3. (Wave siguiente) Plan de adopción sin escritura
ci-pattern adopt <repo> --dry-run

# 4. (Wave siguiente) Adopción real: plantillas + manifiesto + PR
ci-pattern adopt <repo>

# 5. Verificación de cumplimiento tras cualquier cambio
ci-pattern verify <repo> --json
```

Frases de disparo del usuario: «actualizá el sistema de gobernanza»,
«adoptá el patrón en este repo», «verificá el cumplimiento del patrón de CI».
El flujo hoy entrega 1, 2 y 5; 3 y 4 requieren la wave del scaffolder.
