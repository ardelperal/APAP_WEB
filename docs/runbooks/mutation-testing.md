[← Back to README](../../README.md)

# mutation-testing.md

Este runbook cubre el gate de mutation testing basado en cosmic-ray. Aplica al PR #2 de `quality-gates-expansion` (#431).

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican una sesión de mutation testing |
| Lista de comprobación previa | Restricciones de plataforma y de baseline antes de empezar |
| Pasos de despliegue | Secuencia exacta para adquirir o refrescar la baseline |
| Verificación | Lectura del resultado de `check_mutation.py` y de la tabla de fallos |
| Reversión | Desactivación del gate sin pérdida de estado |

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- Una ejecución programada nocturna o semanal del CI (cuando TASK-2.6 conecte el job).
- De forma manual, antes de reforzar las pruebas de un módulo del conjunto objetivo.
- Tras añadir un módulo al conjunto objetivo, para adquirir su entrada de baseline.
- Antes de fusionar un PR que modifique `scripts/check_mutation.py` o `docs/quality/cosmic-ray.toml`.

**Nunca** ejecute el gate dentro de un pull request. Una sesión de cosmic-ray sobre el módulo piloto genera aproximadamente 233 mutantes. El gate mide tendencia, no calidad por commit.

## Lista de comprobación previa

1. **El sistema operativo es Linux.** cosmic-ray 8.4.6 devuelve `INCOMPETENT` para el 100 % de los mutantes en Windows nativo — medido en 27 de 27 sobre un módulo de control de doce líneas y en 233 de 233 sobre `migration/derivation.py`. Mientras tanto, `cr-rate` reporta un `0.00` aprobatorio exactamente para esas sesiones. `mutmut` 3.7.0 rechaza arrancar en Windows (issue upstream boxed/mutmut#397). Sobre una estación Windows, use WSL:

    ```bash
    wsl -d Ubuntu-22.04
    ```

2. **El comando de prueba resuelve sin shell.** cosmic-ray lanza su worker sin shell, por lo que un `python` sin ruta absoluta puede no resolver. Si `cosmic-ray baseline docs/quality/cosmic-ray.toml` imprime un bloque de error, sustituya por una ruta absoluta del intérprete en `test-command` antes de continuar.

3. **La suite sin mutar pasa en verde.** `cosmic-ray baseline` debe imprimir nada. Una baseline fallida invalida todo resultado posterior.

## Pasos de despliegue

Adquiera o refresque la baseline con la siguiente secuencia:

```bash
export PYTHONHASHSEED=0                     # determinismo (TASK-2.1, W-5)
cosmic-ray init docs/quality/cosmic-ray.toml mutation.sqlite
cr-filter-operators mutation.sqlite docs/quality/cosmic-ray.toml
cosmic-ray exec docs/quality/cosmic-ray.toml mutation.sqlite
python scripts/check_mutation.py mutation.sqlite --emit-baseline
```

**Nunca omita `cr-filter-operators`.** Esta herramienta excluye las mutaciones del operador `|` en las anotaciones de tipo PEP 604, que ninguna prueba puede matar porque `from __future__ import annotations` evita la evaluación. En la primera sesión piloto estas mutaciones supusieron 66 de 104 supervivientes reportados. El 63 % de la métrica era ruido que se habría congelado en la baseline como si fuera deuda real.

`--worker-count=1` de TASK-2.1 **no existe**: `cosmic-ray exec` 8.4.6 no acepta esa opción y su distribuidor `local` ya es secuencial.

Guarde el JSON emitido en `docs/quality/mutation-baseline.json` bajo una clave `modules`, y registre en el cuerpo del PR **qué plataforma y runner** lo produjo. Una baseline adquirida fuera del runner Linux de CI no es admisible.

## Verificación

Ejecute el wrapper para evaluar la sesión:

```bash
python scripts/check_mutation.py mutation.sqlite
```

La condición de aprobado es código de salida 0 con el mensaje `check_mutation: OK`.

### Lectura de un fallo

| Mensaje | Significado | Acción |
|---|---|---|
| `came back INCOMPETENT, above the 20% ceiling` | El runner está roto, no el código. Casi siempre: la sesión se produjo en Windows. | Reejecute sobre Linux. **No** ajuste el techo. |
| `0/N mutants were killed` | La suite nunca corrió contra código mutado. | Revise `cosmic-ray baseline` y `test-command`. |
| `session is incomplete` | `cosmic-ray exec` se interrumpió. | Reejecute `exec`; la sesión se reanuda. |
| `grew beyond its baseline` | Regresión real: un cambio añadió mutantes supervivientes. | Refuerce las pruebas, o justifique y re-baserline explícitamente en el PR. |
| `no baseline entry` | Un módulo entró al conjunto objetivo sin pinear. | Añada su entrada vía `--emit-baseline` en el mismo PR. |
| `stale baseline entry` | Un módulo pineado salió del conjunto objetivo o cambió de nombre. | Elimine o actualice la entrada. |

Las dos primeras filas son la razón de ser de este wrapper. `cr-rate --fail-over N` no las distingue de una puntuación perfecta: reporta `0.00` y sale con 0 en ambos casos. Verificado de extremo a extremo el 2026-08-06: sobre la sesión rota de Windows, `cr-rate --fail-over 20` sale con 0 mientras que `scripts/check_mutation.py` sale con 1.

## Reversión

El gate es de sólo lectura sobre la base de datos de la sesión y no toca código de aplicación. Para desactivarlo, retire el paso del CI; no existe estado que deshacer. Eliminar `docs/quality/mutation-baseline.json` provoca que el gate falle cerrado (`baseline not found`) en lugar de aprobar silenciosamente. Ese comportamiento es deliberado.

## Documentos relacionados

- Issue #431 — gate de mutation testing como PR #2 de `quality-gates-expansion`.
- `scripts/check_mutation.py` — wrapper que distingue `INCOMPETENT` de `0/N killed`.
- `docs/quality/cosmic-ray.toml` — configuración de operadores y módulos objetivo.
- `docs/quality/mutation-baseline.json` — baseline pineada (adquirida sólo en runner Linux).