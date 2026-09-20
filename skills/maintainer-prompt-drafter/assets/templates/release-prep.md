# Template: release-prep prompt (MODE=release-prep)

Usá este esqueleto para MODE=`release-prep`. El maintainer prepara un release: tag, changelog, gates, anuncio.

## Estructura base

```markdown
Eres la IA mantenedora de <tool>. Repo: <repo path>. Branch: <release-rama>. Versión: <vN> → <vN+1>.

## Contexto del release

<Qué entra en este release.>
<Diff resumido desde la última release (links a PRs o commits).>
<Rounds cerrados que se incluyen en este release.>

## Gates pre-release (checklist del maintainer)

<Checklist que el maintainer debe cerrar antes de tag:>

- [ ] Tests verdes (`<comando>`).
- [ ] Lint verde (`<comando>`).
- [ ] Coverage ≥ <X>% (si aplica).
- [ ] Type check verde (`<comando>`, si aplica).
- [ ] CHANGELOG actualizado con bullets por cambio.
- [ ] Versión bumped en `<archivo>` (`package.json`, `version.json`, etc.).
- [ ] Migraciones / breaking changes documentadas en `<path>`.
- [ ] <Otros gates específicos del tool>.

## Lo que YA funciona (NO romper)

<Mismas reglas que bug-hunt: lista de capacidades validadas que el release debe preservar.>

## Cambios principales (para el changelog)

<Bulleted list por categoría, estilo Keep-a-Changelog:>

### Added
- <feature nueva> (#issue)

### Changed
- <cambio de comportamiento> (#issue)

### Fixed
- <bug cerrado> (#issue)

### Security
- <cambio de seguridad> (#issue)

### Deprecated
- <deprecation> (#issue)

## Acceptance output

- Tag `<vN+1>` creado y pusheado.
- Release notes en `<path>` (GitHub Releases, CHANGELOG.md, etc.) con los bullets de arriba.
- Anuncio en `<canal>` (Slack, Discord, mailing list, etc.).
- <Otros deliverables específicos>.

## Quick start

```bash
git clone <repo>
cd <repo>
git checkout <release-rama>
<comando test>
<comando lint>
<comando changelog>
<comando tag>
<comando push>
```

## Reinforcement

<Recordatorio de la regla cross-project que el release debe mantener.>
```

## Notas operativas

- **Si el release es breaking**: sumá una sección "## Migration guide" al prompt con instrucciones paso a paso para los consumers.
- **Si hay features experimentales detrás de flags**: documentar la exit criteria en "Acceptance output" (qué tiene que pasar para quitar el flag).
- **Si el release es un hotfix desde `main`**: indicá explícitamente que NO se mergea desde staging; el commit cherry-pickea a `main`, se tagga, y después se mergea `main` de vuelta a staging.
