# cadete — repo settings: allow_auto_merge / allow_update_branch (alineación operador)

- Fecha: 2026-10-01. Task gh-only sobre `DysTelefonica/cadete`, alineada con la regla no-watchers 18 del playbook ci-pattern (el operador aplicó settings idénticos a `ardelperal/APAP_WEB` el mismo día).
- Superficie: ninguna en repo (gh-only). Este fichero es el registro de evidencia.

## Evidencia

1. Read-back antes:
   `gh api repos/DysTelefonica/cadete --jq '{allow_auto_merge,allow_update_branch}'`
   → `{"allow_auto_merge":false,"allow_update_branch":false}` (baseline de la auditoría de gobernanza, OK).
2. PATCH aplicado:
   `gh api -X PATCH repos/DysTelefonica/cadete -f allow_auto_merge=true -f allow_update_branch=true`
   → HTTP 200. En el cuerpo de respuesta `allow_update_branch:true` pero `allow_auto_merge:false` (no era solo staleness).
3. Read-back después (reintentes a +5s, +25s y PATCH dedicado a `allow_auto_merge` +15s):
   → `{"allow_auto_merge":false,"allow_update_branch":true}` — **estable, no es cache**.
4. Sin cambios colaterales:
   `{"delete_branch_on_merge":false,"allow_squash_merge":true,"allow_merge_commit":true,"allow_rebase_merge":true}` — idéntico al baseline de auditoría.

## Friction / causa raíz

`allow_update_branch=true` quedó aplicado. `allow_auto_merge` **no se puede activar** en `DysTelefonica/cadete`: la API responde 200 pero descarta el campo en silencio porque el repo es **privado** y la org `DysTelefonica` está en plan **free** (`gh api orgs/DysTelefonica --jq '.plan'` → `{"filled_seats":4,"name":"free",...}`). Auto-merge en repos privados requiere plan Team/Enterprise (orgs) o Pro (personal). En `ardelperal/APAP_WEB` el mismo comando sí aplicó (`allow_auto_merge:true`) porque es repo de cuenta personal con plan Pro.

Aprendizaje frente a #1150: el stale-read de #1150 se resolvía releyendo; aquí el read-back tras 40s+ y un PATCH dedicado confirman que no es staleness sino feature paywall. Diagnóstico diferencial: comparar con el repo hermano alineado y consultar el plan de la org.

## Pendiente (decisión humana)

- Opción A: dejar `allow_auto_merge=false` en cadete y documentar la divergencia con APAP_WEB hasta que la org escale de plan.
- Opción B: escalar `DysTelefonica` a plan Team (coste) y re-aplicar el mismo PATCH de un flag.
