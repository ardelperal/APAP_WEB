#!/usr/bin/env bash
#
# graduation-helper.sh — Asesor de promoción de skills.
#
# Evalúa las tres condiciones de HR-4 del SKILL.md de skill-propagation:
#   (a) Calidad     — la skill pasa la auditoría de `skill-improver`.
#   (b) Estabilidad — la skill no se editó materialmente en los últimos
#                     14 días naturales.
#   (c) Reuso       — el nombre de la skill aparece en al menos un archivo
#                     bajo una raíz de código (ver GRADUATION_REUSE_ROOTS).
#
# Si las tres pasan, imprime "Veredicto: PASS" y sale 0.
# Si alguna falla, imprime "Veredicto: FAIL (razón: <razón>)" y sale 1.
# Un error de uso (argumentos, skill inexistente, fecha mal formada) sale 2.
#
# Una condición que no se pudo medir cuenta como FAIL: sin fecha de última
# edición falla la estabilidad; sin ninguna raíz de código falla el reuso.
#
# Dispensa de estabilidad: si (b) falla y personal/graduation-waivers.tsv
# contiene una fila válida para la skill, y (a) y (c) pasan, imprime
# "Veredicto: PASS-WITH-WAIVER" con motivo, autorizador y fechas, y sale 0.
# La dispensa nunca cubre (a) ni (c). Una fila de la skill mal formada,
# caducada, futura, de más de 30 días o duplicada no dispensa: si (b) falla,
# el veredicto es "FAIL (razón: waiver_invalid — <causa>)"; si (b) pasa por
# sí sola, la fila solo produce una línea WARN.
#
# Formato de personal/graduation-waivers.tsv: cinco columnas separadas por
# tabulador (skill, reason, authorized_by, granted, expires), fechas como
# YYYY-MM-DD. Las líneas vacías y las que empiezan por `#` se ignoran. Si el
# archivo no existe, no hay dispensas.
#
# La fila de una skill es aquella cuya primera columna es exactamente su
# nombre. Una fila cuya primera palabra es el nombre, pero cuya primera
# columna no lo es (espacios en vez de tabuladores, o blancos delante o
# detrás del nombre), cuenta como fila mal formada de esa skill.
#
# Este script es ASESOR, no actor (HR-8). NO mueve archivos, NO bumpea
# versiones, NO ejecuta refresh-personal-symlinks.sh y NO escribe el archivo
# de dispensas. El operador humano decide tras un veredicto PASS o
# PASS-WITH-WAIVER.
#
# Variables de entorno:
#   GRADUATION_REUSE_ROOTS  Raíces de código separadas por `:`. Sustituye a
#                           las raíces por defecto: /c/00repos/codigo,
#                           C:/00repos/codigo, /mnt/c/00repos/codigo y
#                           $HOME/repos. En Git Bash use la forma /c/...,
#                           porque `:` es el separador. Definida pero vacía,
#                           el reuso falla: no se recurre a las raíces por
#                           defecto.
#   GRADUATION_TODAY        Fecha de hoy como YYYY-MM-DD. Por defecto, la
#                           fecha real. Existe para pruebas deterministas.
#                           Cuando está definida, la salida empieza con un
#                           AVISO que nombra la fecha forzada y la fecha real
#                           del sistema, y la línea de veredicto termina con
#                           " [fecha forzada: YYYY-MM-DD]". Los códigos de
#                           salida no cambian. Un veredicto con esa marca no
#                           es una evaluación real del gate.
#
# Target: Git Bash en Windows y bash en Linux (date de GNU en ambos).
# Uso:    ./graduation-helper.sh <nombre-skill>

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Uso: $0 <nombre-skill>" >&2
  echo "  donde <nombre-skill> es la carpeta bajo personal/ardelperal/" >&2
  exit 2
fi

SKILL_NAME="$1"
SKILL_PATH="personal/ardelperal/${SKILL_NAME}"
SKILL_FILE="${SKILL_PATH}/SKILL.md"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# assets/ -> skill-propagation/ -> skills/ -> raíz del repositorio.
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

if [[ ! -f "${REPO_ROOT}/${SKILL_FILE}" ]]; then
  echo "ERROR: no existe ${SKILL_FILE} (raíz resuelta: ${REPO_ROOT})" >&2
  exit 2
fi

cd "${REPO_ROOT}"

# day_number <YYYY-MM-DD> — imprime los días transcurridos desde el epoch.
# Falla si el argumento no es una fecha real con ese formato.
day_number() {
  local day="$1" secs
  [[ "${day}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
  secs=$(date -u -d "${day}" +%s 2>/dev/null) || return 1
  echo $((secs / 86400))
}

# evaluate_waiver — busca en WAIVERS_FILE la dispensa de estabilidad de la
# skill. Deja el resultado en WAIVER_STATE (none | valid | invalid); si es
# invalid, WAIVER_CAUSE explica la regla incumplida; si es valid, rellena
# WAIVER_REASON, WAIVER_AUTHORIZED_BY, WAIVER_GRANTED y WAIVER_EXPIRES.
WAIVERS_FILE="personal/graduation-waivers.tsv"
WAIVER_MAX_DAYS=30
WAIVER_COLUMNS=(skill reason authorized_by granted expires)
WAIVER_STATE="none"
WAIVER_CAUSE=""
WAIVER_REASON=""
WAIVER_AUTHORIZED_BY=""
WAIVER_GRANTED=""
WAIVER_EXPIRES=""

evaluate_waiver() {
  local line row="" rows=0 inexact_rows=0 inexact_column="" first_column first_word
  local rest index granted_day expires_day span
  local fields=()

  [[ -f "${WAIVERS_FILE}" ]] || return 0

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    [[ -z "${line//[[:space:]]/}" || "${line}" =~ ^[[:space:]]*# ]] && continue
    # Una fila es de la skill si su primera columna es exactamente el nombre.
    first_column="${line%%$'\t'*}"
    if [[ "${first_column}" == "${SKILL_NAME}" ]]; then
      rows=$((rows + 1))
      row="${line}"
      continue
    fi
    # Si la primera palabra es el nombre pero la primera columna no, la fila
    # quiso ser de la skill (espacios en vez de tabuladores, o blancos junto
    # al nombre): falla cerrada en vez de ignorarse.
    first_word="${line#"${line%%[![:space:]]*}"}"
    first_word="${first_word%%[[:space:]]*}"
    if [[ "${first_word}" == "${SKILL_NAME}" ]]; then
      inexact_rows=$((inexact_rows + 1))
      inexact_column="${first_column}"
    fi
  done < "${WAIVERS_FILE}"

  if [[ $((rows + inexact_rows)) -eq 0 ]]; then
    return 0
  fi

  WAIVER_STATE="invalid"

  if [[ $((rows + inexact_rows)) -gt 1 ]]; then
    WAIVER_CAUSE="hay $((rows + inexact_rows)) filas para '${SKILL_NAME}'; debe haber exactamente una"
    return 0
  fi

  if [[ "${inexact_rows}" -eq 1 ]]; then
    WAIVER_CAUSE="la primera columna debe ser exactamente '${SKILL_NAME}' seguida de un tabulador; se leyó '${inexact_column}'"
    return 0
  fi

  # Partir por tabulador conservando las columnas vacías.
  rest="${row}"
  while [[ "${rest}" == *$'\t'* ]]; do
    fields+=("${rest%%$'\t'*}")
    rest="${rest#*$'\t'}"
  done
  fields+=("${rest}")

  if [[ "${#fields[@]}" -ne "${#WAIVER_COLUMNS[@]}" ]]; then
    WAIVER_CAUSE="la fila tiene ${#fields[@]} columnas; se esperan ${#WAIVER_COLUMNS[@]} separadas por tabulador"
    return 0
  fi

  for index in "${!fields[@]}"; do
    if [[ -z "${fields[index]//[[:space:]]/}" ]]; then
      WAIVER_CAUSE="la columna '${WAIVER_COLUMNS[index]}' está vacía"
      return 0
    fi
  done

  if ! granted_day=$(day_number "${fields[3]}"); then
    WAIVER_CAUSE="la columna 'granted' no es una fecha YYYY-MM-DD válida: '${fields[3]}'"
    return 0
  fi
  if ! expires_day=$(day_number "${fields[4]}"); then
    WAIVER_CAUSE="la columna 'expires' no es una fecha YYYY-MM-DD válida: '${fields[4]}'"
    return 0
  fi

  if [[ "${granted_day}" -gt "${TODAY_DAY}" ]]; then
    WAIVER_CAUSE="concedida en el futuro: granted ${fields[3]}, hoy ${TODAY}"
    return 0
  fi
  if [[ "${expires_day}" -lt "${TODAY_DAY}" ]]; then
    WAIVER_CAUSE="caducada: expires ${fields[4]}, hoy ${TODAY}"
    return 0
  fi
  span=$((expires_day - granted_day))
  if [[ "${span}" -gt "${WAIVER_MAX_DAYS}" ]]; then
    WAIVER_CAUSE="vigencia de ${span} días entre granted y expires; el máximo es ${WAIVER_MAX_DAYS}"
    return 0
  fi

  WAIVER_STATE="valid"
  WAIVER_REASON="${fields[1]}"
  WAIVER_AUTHORIZED_BY="${fields[2]}"
  WAIVER_GRANTED="${fields[3]}"
  WAIVER_EXPIRES="${fields[4]}"
}

print_manual_steps() {
  echo "El operador humano debe ejecutar manualmente:"
  echo "  1. Mover la carpeta de personal/ardelperal/${SKILL_NAME}/ a skills/${SKILL_NAME}/"
  echo "  2. Bumpear metadata.version a '1.0' en el frontmatter"
  echo "  3. Ejecutar refresh-personal-symlinks.sh full"
}

STABILITY_DAYS=14
REAL_TODAY="$(date +%F)"
TODAY="${GRADUATION_TODAY:-${REAL_TODAY}}"
if ! TODAY_DAY=$(day_number "${TODAY}"); then
  echo "ERROR: GRADUATION_TODAY debe ser una fecha YYYY-MM-DD (recibido: '${TODAY}')" >&2
  exit 2
fi
# Marca de la línea de veredicto: vacía salvo que la fecha esté forzada.
FORCED_DATE_MARK=""
if [[ -n "${GRADUATION_TODAY:-}" ]]; then
  FORCED_DATE_MARK=" [fecha forzada: ${TODAY}]"
  echo "AVISO: fecha forzada por GRADUATION_TODAY=${TODAY} (fecha real del sistema: ${REAL_TODAY})."
  echo "       El veredicto lleva la marca${FORCED_DATE_MARK} y no es una evaluación real del gate."
  echo
fi

echo "Evaluación de graduación para '${SKILL_NAME}':"
echo

# --- (a) Calidad ---
echo "[1/3] Calidad (auditoría skill-improver)..."
QUALITY_PASS=false
if command -v skill-improver >/dev/null 2>&1; then
  AUDIT_OUTPUT=$(skill-improver --target "${SKILL_FILE}" 2>&1) || true
  if echo "${AUDIT_OUTPUT}" | grep -q 'status: "success"' \
     && echo "${AUDIT_OUTPUT}" | grep -q 'failed_checks: \[\]'; then
    QUALITY_PASS=true
    echo "  Calidad: PASS (skill-improver status=success, 0 failed_checks)"
  else
    echo "  Calidad: FAIL (razón: quality_failed — skill-improver no pasó)"
  fi
else
  # Fallback mínimo cuando skill-improver no está en PATH: frontmatter básico.
  if grep -q '^name:' "${SKILL_FILE}" && grep -q '^description:' "${SKILL_FILE}"; then
    QUALITY_PASS=true
    echo "  Calidad: PASS (verificación mínima — frontmatter OK; skill-improver no disponible)"
  else
    echo "  Calidad: FAIL (razón: quality_failed — falta frontmatter básico)"
  fi
fi
echo

# --- (b) Estabilidad ---
echo "[2/3] Estabilidad (>= ${STABILITY_DAYS} días sin ediciones)..."
STABILITY_PASS=false
LAST_EDIT=$(git log -1 --format=%ct -- "${SKILL_PATH}" 2>/dev/null || true)
if [[ ! "${LAST_EDIT}" =~ ^[0-9]+$ ]]; then
  # Skill sin historial en git: fecha de modificación de la carpeta.
  LAST_EDIT=$(stat -c %Y "${SKILL_PATH}" 2>/dev/null || true)
fi
LAST_EDIT_DAY=""
if [[ "${LAST_EDIT}" =~ ^[0-9]+$ && "${LAST_EDIT}" -gt 0 ]]; then
  LAST_EDIT_DATE=$(date -d "@${LAST_EDIT}" +%F 2>/dev/null || true)
  LAST_EDIT_DAY=$(day_number "${LAST_EDIT_DATE}" || true)
fi
if [[ -z "${LAST_EDIT_DAY}" ]]; then
  echo "  Estabilidad: FAIL (razón: stability_failed — no se pudo determinar la última edición)"
else
  AGE_DAYS=$((TODAY_DAY - LAST_EDIT_DAY))
  if [[ "${AGE_DAYS}" -ge "${STABILITY_DAYS}" ]]; then
    STABILITY_PASS=true
    echo "  Estabilidad: PASS (última edición hace ${AGE_DAYS} días)"
  else
    echo "  Estabilidad: FAIL (razón: stability_failed — última edición hace ${AGE_DAYS} días, umbral ${STABILITY_DAYS})"
  fi
fi
evaluate_waiver
if [[ "${STABILITY_PASS}" == true ]]; then
  if [[ "${WAIVER_STATE}" == invalid ]]; then
    echo "  WARN: fila de dispensa inválida para '${SKILL_NAME}' en ${WAIVERS_FILE} (${WAIVER_CAUSE}); no se consulta porque la estabilidad pasa por sí sola"
  fi
else
  case "${WAIVER_STATE}" in
    valid) echo "  Dispensa: VÁLIDA (concedida ${WAIVER_GRANTED}, caduca ${WAIVER_EXPIRES})" ;;
    invalid) echo "  Dispensa: INVÁLIDA (${WAIVER_CAUSE})" ;;
    *) echo "  Dispensa: ninguna para '${SKILL_NAME}' en ${WAIVERS_FILE}" ;;
  esac
fi
echo

# --- (c) Reuso ---
# Definida pero vacía no recurre a las raíces por defecto: REUSE_ROOTS queda
# sin ninguna raíz y la condición falla más abajo.
if [[ -n "${GRADUATION_REUSE_ROOTS+definida}" ]]; then
  IFS=':' read -r -a REUSE_ROOTS <<< "${GRADUATION_REUSE_ROOTS}"
else
  REUSE_ROOTS=("/c/00repos/codigo" "C:/00repos/codigo" "/mnt/c/00repos/codigo" "${HOME}/repos")
fi

echo "[3/3] Reuso (>= 1 archivo con el nombre de la skill bajo una raíz de código)..."
REUSE_PASS=false
HITS=0
SEARCHED_ROOTS=()
for ROOT in "${REUSE_ROOTS[@]:-}"; do
  [[ -n "${ROOT}" && -d "${ROOT}" ]] || continue
  # Forma canónica: las tres formas Windows nombran el mismo directorio y
  # no deben contarse dos veces.
  CANONICAL_ROOT=$(cd "${ROOT}" 2>/dev/null && pwd -P) || continue
  ALREADY_SEARCHED=false
  for SEEN in "${SEARCHED_ROOTS[@]:-}"; do
    [[ "${SEEN}" == "${CANONICAL_ROOT}" ]] && ALREADY_SEARCHED=true
  done
  [[ "${ALREADY_SEARCHED}" == true ]] && continue
  SEARCHED_ROOTS+=("${CANONICAL_ROOT}")
  ROOT_HITS=$({ grep -rIl --exclude-dir='.git' --exclude-dir='node_modules' -- "${SKILL_NAME}" "${CANONICAL_ROOT}" 2>/dev/null || true; } | wc -l | tr -d ' ')
  HITS=$((HITS + ROOT_HITS))
done
if [[ -n "${GRADUATION_REUSE_ROOTS+definida}" && -z "${GRADUATION_REUSE_ROOTS}" ]]; then
  echo "  Reuso: FAIL (razón: reuse_failed — GRADUATION_REUSE_ROOTS está definida pero vacía; no se usan las raíces por defecto)"
elif [[ "${#SEARCHED_ROOTS[@]}" -eq 0 ]]; then
  echo "  Reuso: FAIL (razón: reuse_failed — no se encontró ninguna raíz de código; se probó: ${REUSE_ROOTS[*]:-})"
elif [[ "${HITS}" -ge 1 ]]; then
  REUSE_PASS=true
  echo "  Reuso: PASS (${HITS} coincidencias en ${SEARCHED_ROOTS[*]})"
else
  echo "  Reuso: FAIL (razón: reuse_failed — 0 coincidencias en ${SEARCHED_ROOTS[*]})"
fi
echo

# --- Veredicto final ---
# La dispensa solo sustituye a la estabilidad; calidad y reuso deciden solos.
REASON=""
if [[ "${QUALITY_PASS}" == false ]]; then
  REASON="quality_failed"
elif [[ "${STABILITY_PASS}" == false && "${WAIVER_STATE}" == invalid ]]; then
  REASON="waiver_invalid — ${WAIVER_CAUSE}"
elif [[ "${STABILITY_PASS}" == false && "${WAIVER_STATE}" != valid ]]; then
  REASON="stability_failed"
elif [[ "${REUSE_PASS}" == false ]]; then
  REASON="reuse_failed"
fi

if [[ -n "${REASON}" ]]; then
  echo "Veredicto: FAIL (razón: ${REASON})${FORCED_DATE_MARK}"
  exit 1
fi

if [[ "${STABILITY_PASS}" == true ]]; then
  echo "Veredicto: PASS${FORCED_DATE_MARK}"
  echo
  print_manual_steps
else
  echo "Veredicto: PASS-WITH-WAIVER${FORCED_DATE_MARK}"
  echo "  Dispensa de estabilidad aplicada:"
  echo "    Motivo:         ${WAIVER_REASON}"
  echo "    Autorizada por: ${WAIVER_AUTHORIZED_BY}"
  echo "    Concedida:      ${WAIVER_GRANTED}"
  echo "    Caduca:         ${WAIVER_EXPIRES}"
  echo
  print_manual_steps
  echo "  4. Retirar la fila de '${SKILL_NAME}' de ${WAIVERS_FILE}"
fi
exit 0
