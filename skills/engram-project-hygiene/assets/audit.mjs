#!/usr/bin/env node
/**
 * engram-project-hygiene — auditor read-only de salud de sincronizacion.
 *
 * NUNCA muta. Abre engram.db en readOnly y usa node:sqlite (Node 22+), que
 * escribe/lee nativo en Windows con el locking WAL de SQLite: no requiere WSL
 * ni copiar el fichero, y por tanto es seguro con otros agentes conectados.
 *
 *   node audit.mjs              # informe legible
 *   node audit.mjs --json       # Output Contract como JSON
 *   node audit.mjs --db <ruta>  # DB alternativa
 */

import { DatabaseSync } from "node:sqlite";
import { execSync } from "node:child_process";
import process from "node:process";

const argv = process.argv.slice(2);
const asJson = argv.includes("--json");
const dbIdx = argv.indexOf("--db");
const DB_PATH =
  dbIdx !== -1 && argv[dbIdx + 1]
    ? argv[dbIdx + 1]
    : `${process.env.USERPROFILE || process.env.HOME}/.engram/engram.db`.replace(/\\/g, "/");

/** Allowlist real del usuario (env var de Windows a nivel User). */
function readAllowlist() {
  const fromEnv = process.env.ENGRAM_CLOUD_ALLOWED_PROJECTS;
  if (fromEnv) return fromEnv.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    const out = execSync(
      "powershell -NoProfile -Command \"[Environment]::GetEnvironmentVariable('ENGRAM_CLOUD_ALLOWED_PROJECTS','User')\"",
      { encoding: "utf8", timeout: 30000 },
    ).trim();
    return out ? out.split(",").map((s) => s.trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

/** Estado del daemon. `last_sync_at` NO es fiable (HR-10): solo informativo. */
async function readDaemon() {
  try {
    const r = await fetch("http://127.0.0.1:7437/sync/status", {
      signal: AbortSignal.timeout(5000),
    });
    const j = await r.json();
    return { phase: j.phase ?? "?", failures: j.consecutive_failures ?? null, enabled: !!j.enabled };
  } catch {
    return { phase: "unreachable", failures: null, enabled: false };
  }
}

const db = new DatabaseSync(DB_PATH, { readOnly: true });
const all = (sql, ...p) => db.prepare(sql).all(...p);
const one = (sql, ...p) => all(sql, ...p)[0];

const allowlist = readAllowlist();
const allowSet = new Set(allowlist);
const inList = allowlist.length ? allowlist.map((p) => `'${p.replace(/'/g, "''")}'`).join(",") : "''";

// --- clases de mutacion que el cloud rechaza -------------------------------
const INVALID = `
  (entity='relation')
  OR (entity_key IS NULL OR entity_key='')
  OR (project IS NULL OR project='')
  OR (entity='prompt' AND op='upsert'
      AND (json_extract(payload,'$.content') IS NULL OR json_extract(payload,'$.content')=''))
  OR (entity='observation' AND op='upsert'
      AND (json_extract(payload,'$.title') IS NULL OR json_extract(payload,'$.title')=''
        OR json_extract(payload,'$.content') IS NULL OR json_extract(payload,'$.content')=''))
`;

const enrolled = all("SELECT project FROM sync_enrolled_projects ORDER BY project").map((r) => r.project);

const counts = (p) => ({
  obs: one("SELECT COUNT(*) c FROM observations WHERE project=?", p).c,
  prompts: one("SELECT COUNT(*) c FROM user_prompts WHERE project=?", p).c,
  sessions: one("SELECT COUNT(*) c FROM sessions WHERE project=?", p).c,
});

// --- estado de los proyectos de la allowlist -------------------------------
const withGap = [];
let inSync = 0;
for (const p of allowlist) {
  const st = one("SELECT last_enqueued_seq,last_acked_seq FROM sync_state WHERE target_key=?", `cloud:${p}`);
  const pending = one("SELECT COUNT(*) c FROM sync_mutations WHERE acked_at IS NULL AND project=?", p).c;
  const gap = st ? st.last_enqueued_seq - st.last_acked_seq : 0;
  if (gap !== 0 || pending > 0) withGap.push(`${p} (gap=${gap}, pendientes=${pending})`);
  else inSync++;
}

// --- enrolados pero bloqueados por la allowlist ----------------------------
const blocked = [];
for (const p of enrolled) {
  if (allowSet.has(p)) continue;
  const c = counts(p);
  if (c.obs + c.prompts + c.sessions > 0) blocked.push({ project: p, ...c });
}
blocked.sort((a, b) => b.obs - a.obs || b.prompts - a.prompts);
const blockedTotals = blocked.reduce(
  (a, r) => ({ projects: a.projects + 1, obs: a.obs + r.obs, prompts: a.prompts + r.prompts, sessions: a.sessions + r.sessions }),
  { projects: 0, obs: 0, prompts: 0, sessions: 0 },
);

// --- mutaciones invalidas --------------------------------------------------
const invalidTotal = one(`SELECT COUNT(*) c FROM sync_mutations WHERE acked_at IS NULL AND (${INVALID})`).c;
const invalidInAllow = one(
  `SELECT COUNT(*) c FROM sync_mutations WHERE acked_at IS NULL AND project IN (${inList}) AND (${INVALID})`,
).c;
const invalidBreakdown = all(`
  SELECT project, entity,
    CASE
      WHEN entity='relation' THEN 'entity=relation (esquema cloud no lo acepta)'
      WHEN entity_key IS NULL OR entity_key='' THEN 'entity_key vacio'
      WHEN project IS NULL OR project='' THEN 'project vacio (HTTP 400)'
      WHEN entity='prompt' THEN 'prompt sin content (HTTP 500)'
      ELSE 'observation sin title/content'
    END AS reason,
    COUNT(*) AS count
  FROM sync_mutations WHERE acked_at IS NULL AND (${INVALID})
  GROUP BY project, entity, reason ORDER BY count DESC`);

// --- candidatos a normalizacion -------------------------------------------
// Heuristica SOLO para proponer. El canonico se confirma leyendo contenido (HR-8).
const projects = all("SELECT DISTINCT project FROM sessions WHERE project IS NOT NULL AND project<>''").map((r) => r.project);
const leaf = (p) => p.replace(/\\+$/, "").split(/[\\/]/).pop().toLowerCase();
const norm = (s) => s.replace(/^00_/, "").replace(/[-_\s]/g, "");

const groups = [];
for (const p of projects) {
  if (!/^[a-z]:[\\/]/i.test(p)) continue; // solo nombres con forma de ruta
  const key = norm(leaf(p));
  const canonical = projects.find((q) => q !== p && !/^[a-z]:[\\/]/i.test(q) && norm(q.toLowerCase()) === key);
  const c = counts(p);
  groups.push({
    fragment: p,
    canonical: canonical ?? null,
    enrolled: canonical ? allowSet.has(canonical) : false,
    evidence: "PENDIENTE: leer sesiones/titulos/prompts antes de reasignar (HR-8)",
    rows: c.obs + c.prompts + c.sessions,
  });
}
groups.sort((a, b) => b.rows - a.rows);

const daemon = await readDaemon();
const integrity = one("PRAGMA integrity_check").integrity_check;
const cloudTarget = one("SELECT lifecycle,consecutive_failures FROM sync_state WHERE target_key='cloud'") ?? {};

const requires = [];
if (blockedTotals.projects > 0) requires.push(`${blockedTotals.projects} proyectos enrolados fuera de la allowlist: la edita el usuario (HR-9)`);
if (groups.some((g) => !g.canonical)) requires.push("Fragmentos sin canonico identificable: requieren clasificacion manual");
if (groups.some((g) => g.canonical && !g.enrolled)) requires.push("Fragmentos cuyo canonico NO esta enrolado: consolidar no los hace sincronizar");

const result = {
  status: invalidInAllow > 0 || withGap.length > 0 ? "blocked" : "success",
  mode: "audit",
  enrolled_count: enrolled.length,
  allowlist_count: allowlist.length,
  allowlisted_in_sync: inSync,
  allowlisted_with_gap: withGap,
  blocked_projects: blocked,
  blocked_totals: blockedTotals,
  invalid_mutations: invalidTotal,
  invalid_breakdown: invalidBreakdown,
  normalization_groups: groups,
  reassigned: [],
  backup_path: null,
  integrity_check: integrity,
  daemon_phase: daemon.phase,
  autosync_verified: false,
  requires_user_decision: requires,
  next_recommended: invalidInAllow > 0 ? "run_sync_doctor" : blockedTotals.projects > 0 ? "edit_allowlist" : "none",
  risks: [
    ...(daemon.phase !== "running" && daemon.phase !== "healthy" ? [`daemon en phase=${daemon.phase}`] : []),
    ...(cloudTarget.consecutive_failures ? [`target cloud con ${cloudTarget.consecutive_failures} fallos`] : []),
    ...(integrity !== "ok" ? [`integrity_check = ${integrity}`] : []),
  ],
};

db.close();

if (asJson) {
  console.log(JSON.stringify(result, null, 2));
} else {
  const p = (s) => console.log(s);
  p("=== ENGRAM PROJECT HYGIENE — AUDITORIA (read-only) ===\n");
  p(`enrolados en la DB: ${result.enrolled_count}   |   allowlist: ${result.allowlist_count}`);
  p(`allowlisted al dia: ${result.allowlisted_in_sync}/${result.allowlist_count}`);
  if (withGap.length) withGap.forEach((g) => p(`   CON GAP: ${g}`));
  p(`\nmutaciones invalidas: ${invalidTotal} (${invalidInAllow} en proyectos de la allowlist)`);
  for (const r of invalidBreakdown) p(`   ${r.project || "(vacio)"} | ${r.entity} | ${r.reason} | ${r.count}`);
  p(`\n--- ENROLADOS PERO BLOQUEADOS POR LA ALLOWLIST ---`);
  p(`${"PROYECTO".padEnd(42)}${"OBS".padEnd(8)}${"PROMPTS".padEnd(9)}SESIONES`);
  for (const b of blocked) p(`${b.project.padEnd(42)}${String(b.obs).padEnd(8)}${String(b.prompts).padEnd(9)}${b.sessions}`);
  p(`TOTAL: ${blockedTotals.projects} proyectos | ${blockedTotals.obs} obs | ${blockedTotals.prompts} prompts | ${blockedTotals.sessions} sesiones`);
  p(`\n--- CANDIDATOS A NORMALIZACION (propuesta, confirmar por contenido) ---`);
  for (const g of groups) p(`${g.fragment}\n   -> ${g.canonical ?? "SIN CANONICO"} | enrolado=${g.enrolled} | filas=${g.rows}`);
  p(`\ndaemon: ${result.daemon_phase}   |   integrity: ${result.integrity_check}   |   status: ${result.status}`);
  if (requires.length) {
    p(`\n--- REQUIERE DECISION DEL USUARIO ---`);
    requires.forEach((r) => p(`   - ${r}`));
  }
  p(`\nsiguiente: ${result.next_recommended}`);
}
