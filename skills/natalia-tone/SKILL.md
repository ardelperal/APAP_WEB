---
name: natalia-tone
description: Trigger: informe para Natalia, mensaje para Natalia, acceptance web para Calidad, status Natalia, comunicar a Natalia. Reports, acceptance webs, and short messages for Natalia (producto, non-technical) in natural Madrid Castilian, no AI-tells, no technical terms.
license: Apache-2.0
metadata:
  author: andres
  version: 1.1
  last_verified: 2026-09-05
  scope: ['universal']
  auto_invoke: ['drafting a report in natalia tone']
  tiers: ['universal']
---



## Activation Contract

Activate when the user asks for:
- An **informe, reporte, demo, validación, prueba** document for **Natalia** (Calidad / Producto).
- A short **mensaje, mail, correo, chat, status** to **Natalia**.
- Anything Calidad needs to **probar, revisar, firmar**.

**Audience profile — Natalia (non-negotiable):**
- **Producto**, no técnica. Recibe el software de desarrollo y lo usa.
- Nunca lee código, PRs, commits, logs, queries, ni nombres de módulos o tablas.
- Lo que necesita saber: **qué ve cuando abre la app, dónde pulsa, qué resultado sale**.

Do NOT activate for:
- Code, docstrings, identifiers, internal specs (English defaults).
- Status for the dev team.
- Anyone other than Natalia.

## Hard Rules — Madrid, no AI, no técnico

**Vocabulario — Madrid España, lenguaje de producto:**
- `ordenador`, `móvil`, `vale`, `oye`, `mira`, `a ver`, `te cuento`, `o sea`, `vamos`, `igual`.
- `tú`/`ti`, registro profesional; nunca `vos`, nunca `ustedes`.
- Estructuras que la gente usa: guiones `—`, paréntesis, elipsis a medias, frases cortas.
- Palabras de producto: `abre`, `pulsa`, `verás`, `la ventana`, `la lista`, `el botón`, `el desplegable`, `el formulario`, `el mensaje que sale`.

**Forbidden AI-tells** — nunca usar, reescribir al vuelo:
- Saludos/cierres: `Estimada Natalia`, `Espero que te sea útil`, `Sin más dilación`, `Sin otro particular`, `Atentamente`, `Quedo a la espera`, `Recibe un cordial saludo`, `Estoy a tu disposición`.
- Cuerpo: `Es importante destacar`, `Cabe mencionar`, `Cabe señalar`, `En este sentido`, `Por lo tanto`, `Para concluir`, `En conclusión`, `En primer lugar`, `A lo largo de este documento`, `Procedo a`, `Me permito`.
- Estructura: listas con simetría perfecta, negrita en cada palabra clave, cierre de tres bullet espejados, párrafo-resumen que repite lo de arriba, cierre de falsa humildad (`Espero que te sirva`, `No dudes en consultarme`).

**Forbidden technical terms** — si aparece en el borrador, reescribir antes de devolver:
- Implementación: `PR`, `sha`, `commit`, `merge`, `branch`, `deploy`, `rollback`, `endpoint`, `API`, `JSON`, `log`, `binario`, `runtime`, `release`.
- Datos/esquema: `tabla`, `campo`, `índice`, `migración`, `columna`, `FK`, `long`, `integer`, `query`, `DAO`, `recordset`.
- Código: `función`, `módulo`, `clase`, `helper`, `procedure`, `manifest`, `test`, `cobertura`, `átomo`.
- Si hace falta un marcador interno (p. ej. de ticket), usar `referencia interna` entre comillas o en nota al pie corta, NO_INLINEAR el código técnico.

**Cierre:** `Un saludo`, `Gracias,` o `Saludos,`. Nunca `atentamente`. Firma solo con el nombre.

**Self-check antes de devolver** — leer en voz alta. Si suena a nota de prensa, a memo corporativo, a resumen de IA, o a status de developer, reescribir. Si suena a un compañero que ha construido la cosa y se la enseña a otro que la va a usar, va.

## Decision Gates

| Formato | Disparadores | Output |
|---------|--------------|--------|
| Acceptance web (HTML) | `informe`, `demo`, `para que valide`, `calculadora`, `prueba` | HTML autocontenido, lead con el saludo humano, 3-5 secciones = pasos que ella hace en la app |
| Mensaje / mail corto | `manda`, `avisa`, `comunica`, `mensaje`, `correo`, `mail`, `chat` | Texto plano, 3-7 frases: qué tiene que pulsar y qué verá, cierra con UNA pregunta |

Si aplican los dos (web + resumen por mail), devolver ambos. Cada uno termina con **una** pregunta clara.

## Execution Steps

1. **Detectar formato** por los disparadores. Si hay duda, preguntar UNA vez.
2. **Si acceptance web HTML:**
   - Lead humano: `Hola Natalia, te paso ...`.
   - Cada sección = **un paso del walkthrough**: abre X, pulsa Y, verás Z.
   - Capturas o pasos numerados; nada de PRs, shas, ni "evidencia técnica".
   - Mostrar primero, explicar-el-código nunca. Comportamiento primero; *por qué* después solo si ella lo pregunta.
   - 3-5 secciones máx; cerrar con **una** pregunta.
3. **Si mensaje:**
   - Resultado primero (`Ya puedes probarlo en staging`), 1-2 frases de contexto, dónde pulsar + qué verá, la pregunta.
   - Texto plano por defecto. Listas de 2-4 items máx.
4. **Tone-check + barrido técnico:** leer en voz alta, matar AI-tells Y términos técnicos. Guardar en `docs/uat/` (o donde diga el usuario).

## Output Contract

Devolver:
- Ruta del artefacto o cuerpo del mensaje.
- Formato elegido y por qué.
- Cualquier párrafo reescrito para matar AI-tells o términos técnicos.
- Confirmación de que el read-aloud + el barrido técnico pasaron.

## References

- `C:\00repos\documentacion\OPENSPEC\00_GESTION_RIESGOS\docs\uat\calculadora-valoracion-riesgos-2026-07-01.html` — ejemplo gold-standard: calculadora que ella toca, sin código.
- `C:\00repos\documentacion\OPENSPEC\00_GESTION_RIESGOS\docs\uat\revision-calidad-para-compartir-2026-06-23.html` — segundo ejemplo, revisión de producto, lenguaje UI-first.
