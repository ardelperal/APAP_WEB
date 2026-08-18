# check_alantyle — linter para anti-patrones documentation-alan-style §10

Detector estático de las nueve formas prohibidas por §10 de la skill `documentation-alan-style` (v2.1). Funciona sobre archivos markdown y no añade dependencias externas: solo la biblioteca estándar de Python.

## Códigos emitidos

| Código | Anti-patrón |
|---|---|
| `ALAN001` | Frontmatter YAML sin los campos obligatorios (`name`, `description`, `license`, `metadata.author`, `metadata.version`). |
| `ALAN002` | Emojis decorativos en headings o cuerpo. |
| `ALAN003` | Secuencias en mayúsculas fuera de los acrónimos whitelisted (`HTTP`, `MCP`, `SQL`, `INSFORGE`, `API`, `PR`, `URL`, `SHA`, más abreviaturas técnicas del repo). |
| `ALAN004` | Lenguaje ambiguo (`we recommend`, `best practice`, `sería bueno`, `podría`, etc.) en lugar de imperativo directo. <!-- alantyle-ignore --> |
| `ALAN005` | Marketing fluff (`amazing`, `powerful`, `world-class`, `game-changer`, etc.). <!-- alantyle-ignore --> |
| `ALAN006` | Más de seis enlaces externos en el mismo archivo. |
| `ALAN007` | Párrafos de más de doscientos caracteres sin punto y aparte. |
| `ALAN008` | Tabla de contenidos auto-generada cerca del top del documento. |
| `ALAN009` | Sección de instalación al final del documento. |

## Uso

```bash
python scripts/check_alantyle.py <ruta> [<ruta>...]
```

`<ruta>` puede ser un archivo `.md` o un directorio (recursivo). Ejemplos:

```bash
python scripts/check_alantyle.py docs/
python scripts/check_alantyle.py README.md AGENTS.md DOCS.md
```

Exit codes:

- `0` cuando no se encuentran violaciones.
- `1` cuando hay violaciones (la lista se imprime en stderr).
- `2` ante un error de uso (sin argumentos).

## Cómo ignorar violaciones

Añada al final de la línea:

```markdown
<!-- alantyle-ignore -->
```

para suprimir todas las detecciones sobre esa línea, o:

```markdown
<!-- alantyle-ignore:ALANxxx -->
```

para suprimir solo el código `ALANxxx`. El marcador se ignora dentro de bloques de código (fenced o indentado).

## Detalles por detector

ALAN001 solo se aplica a archivos que abren con un frontmatter YAML entre dos líneas `---`. Los archivos sin frontmatter no disparan este código.

ALAN002 detecta code-points de emojis en cualquier línea fuera de un bloque de código que no esté ignorada. La regex interna cubre BMP (`U+2600`-`U+26FF`) y supplementary planes (`U+1F300`-`U+1FAFF`, `U+1F1E6`-`U+1F1FF`).

ALAN003 busca palabras de 2+ letras ASCII en mayúsculas que no estén en la whitelist. La whitelist incluye los siete acrónimos de la skill §10 más abreviaturas técnicas del repo (`CI`, `MVP`, `OK`, `YAML`, `JSON`, `HTML`, `CSS`, `XML`, `CSV`, `TOML`, `ASCII`, `BMP`, `TOC`, `ADR`, `SDK`, `AST`, `UTF`) y nombres propios de archivos raíz (`README`, `AGENTS`, `DOCS`, `CODEBASE`, `GUIDE`, `CHANGELOG`, `CONTRIBUTING`, `OPENSPEC`, `PROBLEMS`). Secuencias seguidas de dígitos (como `ALAN001` o `SHA256`) no se contabilizan porque no hay límite de palabra entre la letra final y el dígito inicial.

ALAN004 reporta la primera frase ambigua por línea para no inundar la salida. Operadores pueden reescribir y re-correr.

ALAN005 acepta comentarios HTML `<!-- ... -->` por línea como mecanismo de escape.

ALAN006 cuenta enlaces externos `http://` o `https://` por archivo y emite una sola violación (en el primer enlace que supera el umbral).

ALAN007 mide el párrafo como la concatenación de líneas no vacías no indentadas como heading. Headings rompen el párrafo.

ALAN008 busca los marcadores en las primeras cincuenta líneas del documento.

ALAN009 activa cuando el heading `## Installation` o `## Install` aparece en o después de la línea `total // 2`.

## Ver también

- Skill `documentation-alan-style` §10 — definición canónica de los anti-patrones.
- `tests/test_check_alantyle.py` — cobertura por detector.
- `.github/workflows/ci.yml` — integración en el job `lint` (con `continue-on-error: true` durante el rollout inicial; ver ADR d-42).
- ADR d-42 — decisión de rollout del detector.