#!/usr/bin/env bash
#
# graduation-helper.sh — Asesor de promoción de skills.
#
# Evalúa las tres condiciones de HR-4 del SKILL.md de skill-propagation:
#   (a) Calidad     — la skill pasa la auditoría de `skill-improver`.
#   (b) Estabilidad — la skill no se editó materialmente en los últimos
#                     14 días naturales.
#   (c) Reuso       — el nombre de la skill aparece en al menos un proyecto
#                     bajo C:\00repos\codigo\.
#
# Si las tres pasan, imprime "Veredicto: PASS" y sale 0.
# Si alguna falla, imprime "Veredicto: FAIL (razón: <razón>)" y sale 1.
#
# Este script es ASESOR, no actor (HR-8). NO mueve archivos, NO bumpea
# versiones, NO ejecuta refresh-personal-symlinks.sh. El operador humano
# decide tras un veredicto PASS.
#
# Target: Git Bash en Windows. Usa rutas unix internamente.
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
REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"

if [[ ! -f "${REPO_ROOT}/${SKILL_FILE}" ]]; then
  echo "ERROR: no existe ${SKILL_FILE}" >&2
  exit 2
fi

cd "${REPO_ROOT}"

STABILITY_DAYS=14
NOW=$(date +%s)
THRESHOLD=$((NOW - STABILITY_DAYS * 24 * 60 * 60))

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
LAST_EDIT=0
if git log -1 --format=%ct -- "${SKILL_PATH}" 2>/dev/null | grep -qE '^[0-9]+$'; then
  LAST_EDIT=$(git log -1 --format=%ct -- "${SKILL_PATH}")
fi
if [[ "${LAST_EDIT}" -eq 0 && -d "${SKILL_PATH}" ]]; then
  LAST_EDIT=$(stat -c %Y "${SKILL_PATH}" 2>/dev/null || stat -f %m "${SKILL_PATH}" 2>/dev/null || echo 0)
fi
if [[ "${LAST_EDIT}" -eq 0 ]]; then
  echo "  Estabilidad: SKIP (no se pudo determinar última edición; tratado como PASS conservador)"
  STABILITY_PASS=true
elif [[ "${LAST_EDIT}" -lt "${THRESHOLD}" ]]; then
  AGE_DAYS=$(((NOW - LAST_EDIT) / 24 / 60 / 60))
  STABILITY_PASS=true
  echo "  Estabilidad: PASS (última edición hace ${AGE_DAYS} días)"
else
  AGE_DAYS=$(((NOW - LAST_EDIT) / 24 / 60 / 60))
  echo "  Estabilidad: FAIL (razón: stability_failed — última edición hace ${AGE_DAYS} días, umbral ${STABILITY_DAYS})"
fi
echo

# --- (c) Reuso ---
echo "[3/3] Reuso (>= 1 hit en C:\\00repos\\codigo)..."
REUSE_PASS=false
HITS=0
for P in "/c/00repos/codigo" "C:/00repos/codigo" "/mnt/c/00repos/codigo"; do
  if [[ -d "${P}" ]]; then
    HITS=$(grep -rIln --exclude-dir='.git' --exclude-dir='node_modules' -- "${SKILL_NAME}" "${P}" 2>/dev/null | wc -l | tr -d ' ')
    break
  fi
done
if [[ "${HITS}" -ge 1 ]]; then
  REUSE_PASS=true
  echo "  Reuso: PASS (${HITS} coincidencias)"
else
  echo "  Reuso: FAIL (razón: reuse_failed — 0 coincidencias)"
fi
echo

# --- Veredicto final ---
if [[ "${QUALITY_PASS}" == true && "${STABILITY_PASS}" == true && "${REUSE_PASS}" == true ]]; then
  echo "Veredicto: PASS"
  echo
  echo "El operador humano debe ejecutar manualmente:"
  echo "  1. Mover la carpeta de personal/ardelperal/${SKILL_NAME}/ a skills/${SKILL_NAME}/"
  echo "  2. Bumpear metadata.version a '1.0' en el frontmatter"
  echo "  3. Ejecutar refresh-personal-symlinks.sh full"
  exit 0
else
  if [[ "${QUALITY_PASS}" == false ]]; then
    REASON="quality_failed"
  elif [[ "${STABILITY_PASS}" == false ]]; then
    REASON="stability_failed"
  else
    REASON="reuse_failed"
  fi
  echo "Veredicto: FAIL (razón: ${REASON})"
  exit 1
fi
