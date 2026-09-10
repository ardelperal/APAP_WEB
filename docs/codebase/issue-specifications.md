[Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Contrato de especificaciones de issues

**Toda implementación humana parte de una issue aprobada que permite verificar problema, evidencia, alcance, aceptación, validación y riesgos sin reconstruir decisiones.**

Este contrato gobierna las issues nuevas. El histórico anterior a la issue #723 se conserva como evidencia y se audita sin inventar información ausente.

## Who this is for
| Reader | Use this guide to |
|---|---|
| Autor de una issue | Convertir una necesidad en una spec ejecutable. |
| Mantenedor | Aprobar solo issues con alcance y verificación suficientes. |
| Implementador | Saber qué entregar y qué no modificar. |
| Revisor | Rastrear cada cambio hasta un criterio verificable. |

## Quick path
1. Elija el formulario que coincide con el único label `type:*` del trabajo.
2. Complete las seis secciones con hechos y límites comprobables.
3. Obtenga `status:approved` antes de crear la rama.
4. Enlace el PR mediante `Closes #N`, `Fixes #N` o `Resolves #N`.
5. Ejecute `make check-issue-specs` y espere `ci / required` en verde.

## Core invariants
- **Una fuente**: el cuerpo de la issue posee la spec de ejecución; OpenSpec amplía cambios estructurales, pero no la sustituye.
- **Sin invención retroactiva**: una laguna histórica se marca como ausente o no inferible. Nunca se rellena con una suposición.
- **Aprobación humana**: el gate comprueba `status:approved`; no lo concede ni lo infiere.
- **Todos los cierres**: cada issue que un PR declare que cerrará debe cumplir el contrato.
- **Aislamiento**: el job usa un runner efímero y un token de solo lectura; no recibe secretos ni permisos de escritura.

## Contrato del cuerpo
| Sección H3 | Responde | Evidencia mínima |
|---|---|---|
| `Problema y contexto` | Qué falla o falta, dónde y para quién. | Comportamiento actual concreto. |
| `Evidencia verificable` | Qué demuestra la necesidad. | Ruta, reproducción, dato o fuente canónica. |
| `Alcance y no objetivos` | Qué cambia y qué queda fuera. | Dos límites explícitos. |
| `Criterios de aceptación` | Qué resultado autoriza el cierre. | Lista de resultados observables. |
| `Plan de validación` | Cómo se probará cada criterio. | Tests, comandos o recorrido manual. |
| `Dependencias y riesgos` | Qué bloquea o puede romperse. | Dependencias, rollback o «Ninguno». |

Los cinco formularios YAML contienen estas secciones como `textarea` obligatorio. GitHub impide enviarlas vacías y `config.yml` desactiva las issues en blanco.

## Responsabilidades por superficie
| Surface | Owns | Does not own |
|---|---|---|
| Formularios YAML | Captura obligatoria y label de tipo. | Calidad semántica de la respuesta. |
| `check_issue_specs.py forms` | Forma, tipos soportados y prohibición de blank issues. | Estado remoto de una issue. |
| Job `issue-spec` de `ci.yml` | Referencias de cierre, tipo único y aprobación. | Conceder labels o acceder a secretos. |
| Revisión humana | Verdad, suficiencia y decisiones de producto. | Repetir comprobaciones mecánicas. |
| OpenSpec | Requisitos y diseño de cambios estructurales. | Autorizar trabajo sin issue aprobada. |

Los PR de Dependabot son la única excepción automática. Su intención procede de `.github/dependabot.yml` y no de una issue escrita por una persona.

## Histórico anterior al contrato
[`docs/quality/issue-spec-baseline.jsonl`](../quality/issue-spec-baseline.jsonl) registra las 308 issues hasta la #722, inclusive.

Cada fila conserva URL, título, estado, tipo inferible, hash del cuerpo, secciones canónicas, señales semánticas y lagunas. No copia el cuerpo.

| Value | Meaning |
|---|---|
| `present` / `absent` | La sección canónica existe con contenido o no existe. |
| `detected` | El cuerpo contiene una señal semántica reconocible. |
| `not-inferable` | El dato no puede demostrarse mecánicamente; no significa que nunca existiera. |
| `workflow_ready` | Coinciden cuerpo, tipo único y aprobación del contrato actual. |

La línea base no convierte las issues cerradas en specs nuevas. Conserva su trazabilidad y muestra con precisión qué evidencia sobrevivió.

## Reparar una issue histórica
1. Lea el cuerpo, comentarios, commits y PR vinculados.
2. Recupere solo hechos demostrables y cite su origen.
3. Reescriba el cuerpo con las seis secciones sin alterar la intención original.
4. Solicite revisión humana para cualquier decisión que siga abierta.
5. Aplique `status:approved` únicamente después de esa revisión.

No implemente una issue histórica que el gate marque incompleta. Primero repárela en GitHub; después abra o actualice el PR.

## Comandos
```bash
# Validar los formularios versionados.
make check-issue-specs

# Regenerar el snapshot histórico fijado en la issue #722.
GITHUB_TOKEN="$(gh auth token)" python scripts/check_issue_specs.py baseline \
  --repository ardelperal/APAP_WEB --cutoff 722 --as-of 2026-09-09 \
  --output docs/quality/issue-spec-baseline.jsonl
```

## Contributor checklist
- [ ] El formulario corresponde al único `type:*` de la issue.
- [ ] Las seis secciones contienen hechos, límites y resultados verificables.
- [ ] OpenSpec enlaza la issue cuando el cambio es estructural.
- [ ] El PR usa una referencia de cierre y no una mención informal.
- [ ] La línea base solo cambia mediante el generador documentado.
- [ ] Ningún dato ausente se ha completado por inferencia.

## Navigation
Previous: [Maintainer playbook](maintainer-playbook.md) | Next: [CI/CD](ci-cd.md)
