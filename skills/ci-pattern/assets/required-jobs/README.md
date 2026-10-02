# required-jobs — agregador fail-closed de jobs requeridos

Primer asset ejecutable de `ci-pattern` (issue DysTelefonica/team-skills#132).
Sustituye al `check_required_jobs.py` del consumer de origen: la lógica es la
misma, pero ningún nombre de job, evento o skip vive en el código — todo eso
es política (`required-jobs.policy.example.json` como molde de ejemplo).

## Contenido

| Fichero | Papel |
|---|---|
| `check_required_jobs.py` | Gate: verdicto fail-closed sobre el objeto `needs` serializado |
| `required-jobs.policy.example.json` | Política de ejemplo: jobs conocidos y skips aceptados por evento |
| `tests/` | Suite ejecutable (solo stdlib): veredictos, fail-closed y paridad workflow↔política |

## Destino en el consumer

Copie el directorio a `scripts/required-jobs/` del repo consumer (o la ruta
equivalente) y versione allí su propia política; la de ejemplo es un molde,
no una configuración. No hay nada más que instalar: el gate es stdlib-only.

## Cableado del job agregador

```yaml
required:
  needs: [lint, compile, smoke, unit, full]   # la misma lista que la política declara
  if: always()
  steps:
    - uses: actions/checkout@v4
    - run: |
        echo '${{ toJSON(needs) }}' > needs.json
        python3 scripts/required-jobs/check_required_jobs.py \
          --policy scripts/required-jobs/required-jobs.policy.json \
          --event '${{ github.event_name }}' \
          --needs-file needs.json
```

`toJSON(needs)` serializa el objeto `needs` del job agregador; el gate lo lee
por `--needs-file` o por stdin. Marque `required` como check requerido en la
protección de rama. El veredicto es fail-closed: entrada ilegible, evento no
declarado, job conocido ausente de `needs`, clave de `needs` no cubierta por
la política, skip no declarado o conclusión `failure`/`cancelled` salen por
exit 1. La salida separa causas raíz (`failure`/`cancelled`) de skips en
cascada, para que un skip descendente nunca se lea como la causa.

## Tests

```bash
python3 scripts/required-jobs/tests/test_required_jobs.py
```
