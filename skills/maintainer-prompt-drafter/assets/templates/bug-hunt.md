# Template: bug-hunt prompt (MODE=bug-hunt)

Usá este esqueleto para MODE=`bug-hunt`. Cada sección tiene un rol concreto descrito al lado.

## Estructura base

```markdown
Eres la IA mantenedora de <tool>. Repo: <repo path>. Branch: <fix-rama-sugerida>. Versión: <vN>.

## Contexto del round

<1-2 frases. Si round>1, mencionar rounds anteriores en UNA línea cada uno, con su resolución.>

Ejemplo (round 3, dysflow):
> Round 3 = un único gap bloqueante para introspection de DAO schema sin abrir Access manualmente.
> Rounds previos:
> - Round 1: capabilities block migration (CONFIG_TOP_LEVEL_FIELDS_REMOVED) — cerrado.
> - Round 2: correcciones de seguridad + scope (mantenedor respondió a round 1) — cerrado.

## Lo que YA funciona (NO tocar)

<Lista corta de capacidades VALIDADAS por el consumer en este round. Si el tool tiene muchas, agrupá por familia:
`get_*` tools, `*_tools`, `lint_*`, TDD gates, capabilities flags, etc.>

Importante: incluir el **comportamiento intencional** que NO se debe cambiar. Ejemplo:
> NO reintroducir la tool `compile_vba` (su eliminación es intencional, parte de la regla cross-project "human compiles").

## Lo que falta en este round

<Para CADA gap, una sub-sección con este esqueleto:>

### Bug <N>: <título de una línea>

#### Síntoma verificado

<Una frase describiendo qué ve el consumer. Sin "creo", sin "maybe". Solo hechos.>

#### Evidencia de repro

<Pegar logs/errores literales. NO parafrasear. Si hay JSON de respuesta del tool, pegarlo completo.>

#### Diagnóstico preliminar (opcional)

<Hipótesis sobre root cause. Marcar como preliminar si NO está verificado.>
<Listar posibles root causes numeradas (1, 2, 3...). El maintainer confirma o descarta.>

#### Riesgo

<Impacto en el consumer y/o en otros consumers del fleet. Cuantificar si es posible.>

#### Tests RED sugeridos

<1-3 tests concretos. Pseudocódigo o casos. Cada test debe valer RED → GREEN por sí solo.>

Formato típico:
```ts
it('<descripción>', async () => {
  const result = await client.call('<tool>', { ... });
  expect(result.ok).toBe(true);     // esperado
  // actualmente falla con: <error literal>
});
```

## Disciplina

- TDD estricto (RED → GREEN → REFACTOR).
- Conventional commits con scope apropiado (`<area>` o `<subsystem>`).
- NO tocar las herramientas/capabilities de rounds anteriores (citá cuáles en "Lo que YA funciona").
- <Otras reglas específicas del tool si las conocés>.

## Acceptance output

- PR con <X> tests verdes.
- Changelog en `<path>` con bullet: `<descripción del fix> (#<issue>)`.
- Version bump: patch (`vN+1`) si el gap es chico, minor (`vN+1.0`) si cambia comportamiento o surface, major (`v(N+1).0.0`) si rompe compat.
- <Otras entregas del maintainer: docs actualizados, ejemplo agregado a `verify-examples-vs-runtime.<ext>`, etc.>

## Quick start

```bash
git clone <repo path>
cd <repo>
git checkout -b <fix-rama-sugerida>
<comando install — pnpm install, npm install, etc.>
<comando dev — pnpm run dev, npm run dev, etc.>
```

Test repro contra el dev:
```bash
<comando exacto que reproduce el bug>
# Esperado: <output correcto>
# Actual: <output del bug>
```

## Reinforcement

<Recordatorio de la regla cross-project que el fix debe mantener, en 1-2 frases. Si el fix no la cumple, escalar a siguiente round.>
```

## Notas operativas

- **Variant short** = drop `Diagnóstico preliminar`, `Riesgo` y `Reinforcement`. Mantené solo Síntoma, Evidencia, Test RED, Quick start.
- **Variant long** = sumá un "## Dependencies / blockers" si hay gates cruzados con otros rounds abiertos.
- **Si un mismo round tiene ≥3 bugs**: considerá mover a `release-prep` con varios fixes juntos.
