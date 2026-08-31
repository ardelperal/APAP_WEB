# Skills de APAP_WEB

Las skills que este proyecto necesita viven aquí, versionadas junto al código.
Quien clona el repositorio las tiene.

## Contrato

Las skills versionadas en este directorio son la **fuente canónica** dentro del
proyecto. El AGENTS.md las referencia por path local, no por path global.

Sólo pueden asumirse instalados dos harness externos:

| Harness | Qué aporta |
|---|---|
| `gentle-ai` | 26 skills, entre ellas `branch-pr`, `chained-pr`, `work-unit-commits`, `issue-creation` y la suite `sdd-*` |
| `engram` | Memoria persistente entre sesiones |

Las skills con prefijo `apap-` que viven en `~/.config/opencode/skills/` de una
máquina local son **fallback legacy** — si una convención del proyecto necesita
una de esas skills, está en este directorio, no en la máquina del operador.

## Catálogo

| Skill | Cuándo cargarla |
|---|---|
| `apap-testing-strategy` | Decidir tipo de test (unit/integration/e2e/migration), auditar gaps, refactorizar mocks a integration real. Basada en el audit 2026-08-31. Complementaria a `apap-testing`. |

## Cómo se carga

Una IA que abre el repo debe:

1. Leer `AGENTS.md` §Project-context skills para descubrir los paths.
2. Cargar la skill leyendo `skills/<nombre>/SKILL.md` con la herramienta `read`.
3. Seguir los patrones y reglas de la skill cargada.

Las IAs no leen `skills/` directamente sin pasar por AGENTS.md; el índice en
AGENTS.md es el contrato de discovery.

## Cómo se mantienen

- Toda skill nueva nace con la disciplina `skill-style-guide`: frontmatter
  prescrito, body budget ≤ 700 líneas, secciones canónicas §N en orden,
  hard rules numeradas HR-N con verbos observables, decision gates y
  anti-patterns en tabla, output contract con tabla de keys.
- Cada edición material debe actualizar `metadata.last_verified`.
- Toda skill nueva se registra en AGENTS.md §Project-context skills en el
  mismo PR que la introduce.