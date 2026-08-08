[← Back to README](../../README.md)

# github-runner-registration.md

Este runbook es el procedimiento del operador para registrar, verificar y dar de baja el runner auto-hospedado Oracle ARM64 del job `e2e` y el workflow `e2e (self-hosted)`. Aplica al issue #223.

## Quick Navigation

| Sección | Propósito |
|---|---|
| Estado actual de producción | Tabla de propiedades confirmadas del runner |
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Lista de comprobación previa | Verificaciones de conectividad, token y aislamiento respecto a Cadete |
| Pasos de despliegue | Procedimiento de registro, configuración y verificación |
| Diagnóstico del runner | Comprobaciones cuando el runner aparece Offline |
| Recuperación tras reinicio | Procedimiento tras un reboot de la VPS |
| Baja y reversión | Procedimiento para eliminar el runner |
| Secretos y credenciales | Variables de GitHub requeridas y opcionales |

## Estado actual de producción

| Propiedad | Valor confirmado |
|---|---|
| Usuario del runner | `ubuntu` (no root, no github-actions) |
| Directorio raíz del runner | `/home/ubuntu/github-runner/apap-web/` |
| Unidad systemd | `github-runner-apap-web.service` |
| Etiquetas (exactas, obligatorias) | `self-hosted`, `Linux`, `ARM64`, `apap`, `oracle` |
| Grupo del runner | `Default` (con ámbito de repositorio) |
| Arquitectura | Oracle ARM64 (Ampere Altra) |
| Repositorio GitHub | `ardelperal/APAP_WEB` |

El runner vive en la VPS Oracle ARM64 que también aloja Cadete. Se mantiene **estrictamente aislado** de Cadete: directorio de runner separado, unidad systemd separada, sin credenciales compartidas, sin acceso sudo.

## Cuándo abrir este runbook

Abra este runbook en las siguientes situaciones:

- Aprovisionamiento de un **runner** auto-hospedado nuevo por primera vez.
- Verificación de un **runner existente** tras un reinicio de la VPS.
- Re-registro del runner tras un cambio de hostname o IP de la VPS.
- **Baja** del runner (por ejemplo, antes de una reconstrucción de la VPS).
- Ejecución de la programación semanal de smoke-test (workflow `e2e (self-hosted)`).

## Lista de comprobación previa

Antes de registrar o re-registrar:

- [ ] Confirme que dispone de una conexión SSH funcional a la VPS Oracle ARM64 como `ubuntu` (el usuario administrador con sudo).
- [ ] Confirme que la VPS es alcanzable desde GitHub Actions (sin VPN, sin firewall que bloquee el puerto 443 saliente hacia `github.com`).
- [ ] Obtenga el **token de registro del runner** desde GitHub: `Settings → Actions → Runners → New self-hosted runner → copie el comando de registro (contiene el token)`. El token es de corta duración; complete el registro en menos de treinta minutos.
- [ ] Confirme que ningún otro runner en esta VPS usa el mismo directorio de runner (`/home/ubuntu/github-runner/apap-web/`). Compartir el directorio entre runners provoca conflictos en la asignación de jobs.
- [ ] Confirme que el directorio del runner de Cadete permanece intacto: `ls /home/ubuntu/github-runner/cadete/` existe y su unidad es `github-runner-cadete.service`. **Nunca reutilice el directorio ni la unidad de Cadete.**
- [ ] Verifique que `python3 --version` en la VPS devuelve Python >= 3.11 (coincide con `python-version-file: pyproject.toml` en ci.yml).
- [ ] Confirme que `playwright install chromium` se ha ejecutado al menos una vez en la cuenta del usuario del runner (o que el job e2e lo instala en tiempo de ejecución — lo hace, por lo que este punto es opcional).

## Pasos de despliegue

### 1. Conexión SSH a la VPS

```bash
ssh ubuntu@<vps-ip-or-hostname>
```

### 2. Creación del directorio del runner

```bash
sudo mkdir -p /home/ubuntu/github-runner/apap-web
sudo chown ubuntu:ubuntu /home/ubuntu/github-runner/apap-web
# Verifique la separación respecto a Cadete
ls /home/ubuntu/github-runner/
# Salida esperada: cadete/  apap-web/
```

### 3. Descarga del runner de GitHub Actions

```bash
cd /home/ubuntu/github-runner/apap-web
# Descargue la última versión linux-arm64 (consulte https://github.com/actions/runner/releases)
curl -L -o actions-runner-linux-arm64-latest.tar.gz \
  https://github.com/actions/runner/releases/download/v2.323.0/actions-runner-linux-arm64-2.323.0.tar.gz
tar xzf actions-runner-linux-arm64-latest.tar.gz --strip-components=1
rm actions-runner-linux-arm64-latest.tar.gz
```

> **Nota:** Reemplace `v2.323.0` por la versión vigente en `https://github.com/actions/runner/releases`. El binario ARM64 es `actions-runner-linux-arm64-<version>.tar.gz`.

### 4. Configuración del runner

```bash
cd /home/ubuntu/github-runner/apap-web
./config.sh \
  --url https://github.com/ardelperal/APAP_WEB \
  --token <REGISTRATION_TOKEN> \
  --labels "self-hosted,Linux,ARM64,apap,oracle" \
  --runnergroup Default \
  --work _work \
  --unattended \
  --replace
```

Banderas clave:

- `--labels`: debe incluir **las cinco** etiquetas exactamente como se muestran. GitHub Actions asocia jobs a runners por etiqueta; las coincidencias parciales **no** funcionan.
- `--replace`: use sólo al re-registrar un runner existente (por ejemplo, tras la expiración del token). Elimina el registro antiguo y vuelve a registrar con el token nuevo.
- `--unattended`: evita las preguntas interactivas (seguro para uso con systemd).

### 5. Instalación y habilitación del servicio systemd

```bash
sudo ./svc.sh install ubuntu
sudo ./svc.sh start
```

Verifique:

```bash
systemctl status github-runner-apap-web.service
# Esperado: active (running)
sudo journalctl -u github-runner-apap-web.service -f --since "2 minutes ago"
```

### 6. Verificación de que el runner aparece en GitHub

1. Vaya a `https://github.com/ardelperal/APAP_WEB → Settings → Actions → Runners`.
2. Confirme que el runner `apap-web` aparece bajo **Self-hosted runners** con las cinco etiquetas y el estado **Idle** (u **Online** si un job acaba de ejecutarse).
3. Si el estado es **Offline**, consulte la sección de diagnóstico del runner más abajo.

### 7. Ejecución del script de comprobación de conectividad

Desde su **máquina local** (no la VPS):

```bash
./scripts/check-runner.ps1 -RunnerUrl "https://github.com/ardelperal/APAP_WEB" -Labels "self-hosted,Linux,ARM64,apap,oracle"
```

Salida esperada: el runner es alcanzable, tiene las etiquetas esperadas y se encuentra en estado **Idle** u **Online**.

## Diagnóstico del runner

Si el runner aparece **Offline** en GitHub:

### En la VPS

```bash
# Compruebe el estado del servicio
systemctl status github-runner-apap-web.service

# Vea los registros recientes
sudo journalctl -u github-runner-apap-web.service -n 50 --no-pager

# Compruebe el proceso del runner
ps aux | grep '[g]ithub-runner'

# Compruebe la accesibilidad de red
curl -s --max-time 10 https://github.com
curl -s --max-time 10 https://objects.githubusercontent.com
```

### Correcciones habituales

**Token expirado**: re-registre con `config.sh --replace` y un token nuevo.

**Puerto 443 bloqueado saliente**: configure el firewall de la VPS para permitir TCP 443 saliente hacia `github.com` y `objects.githubusercontent.com`.

**Conflicto de directorio del runner**: si el runner de Cadete también apunta a `/home/ubuntu/github-runner/apap-web/`, sus jobs robarán las asignaciones de este runner. Asegúrese de que el `run.sh` o `svc.sh` de Cadete apunta a un directorio distinto (`/home/ubuntu/github-runner/cadete/`).

## Recuperación tras reinicio

El servicio systemd está configurado para arrancar automáticamente tras un reinicio (`WantedBy=multi-user.target` mediante `./svc.sh install`). Para verificar:

```bash
# Simule un reinicio
ssh ubuntu@<vps-ip> "sudo systemctl restart github-runner-apap-web.service"
# Espere diez segundos
sleep 10
# Compruebe el estado
ssh ubuntu@<vps-ip> "systemctl status github-runner-apap-web.service"
# Verifique que el runner está en línea en GitHub Settings → Actions → Runners
```

Si el runner **no** vuelve a estar en línea tras un reinicio real de la VPS:

1. Conéctese por SSH a la VPS.
2. Compruebe `systemctl status github-runner-apap-web.service`.
3. Si el servicio está fallido, re-ejecute `./svc.sh install && ./svc.sh start`.
4. Si el proceso está en ejecución pero GitHub muestra Offline, el token de registro puede haber expirado — re-registre con `config.sh --replace`.

## Baja y reversión

Para eliminar el runner de forma permanente (por ejemplo, antes de una reconstrucción de la VPS):

### En la VPS

```bash
cd /home/ubuntu/github-runner/apap-web
sudo ./svc.sh stop
sudo ./svc.sh uninstall
cd ..
sudo rm -rf /home/ubuntu/github-runner/apap-web
```

### En GitHub

1. Vaya a `https://github.com/ardelperal/APAP_WEB → Settings → Actions → Runners`.
2. Localice el runner `apap-web`.
3. Pulse el menú de elipsis → **Remove runner**. Esta acción elimina el runner del registro de GitHub e impide asignaciones de jobs obsoletas.

### Tras la baja

- El job e2e en `ci.yml` volverá automáticamente a `ubuntu-latest` porque `APAP_SELF_HOSTED_E2E_ENABLED` ya no enrutará jobs al runner auto-hospedado inexistente. No se requiere cambio de YAML.
- El workflow `e2e-self-hosted.yml` saltará todos sus jobs silenciosamente (su condición `if` verifica `vars.APAP_SELF_HOSTED_E2E_ENABLED != ''`).

## Secretos y credenciales

El runner **no requiere secretos adicionales** más allá de lo que el job e2e ya necesita:

| Secreto / Variable | ¿Existe ya? | Uso |
|---|---|---|
| `APAP_OAUTH_CLIENT_ID` | Sí (variable de repositorio) | Compuerta OAuth en el job e2e de ci.yml |
| `APAP_GOOGLE_CLIENT_SECRET` | Sí (secreto de repositorio) | Flujo OAuth en pruebas e2e |
| `APAP_SELF_HOSTED_E2E_ENABLED` | No — **créela** | Controla `runs-on` en el job e2e de ci.yml |

### Creación de `APAP_SELF_HOSTED_E2E_ENABLED`

En GitHub: `Settings → Actions → Variables → New variable`:

- **Name**: `APAP_SELF_HOSTED_E2E_ENABLED`
- **Value**: `1` (cualquier cadena no vacía habilita el runner auto-hospedado)
- **Description**: `Enables the self-hosted Oracle ARM64 runner for the e2e job (issue #223)`

> Sin esta variable, el job e2e en `ci.yml` vuelve a `ubuntu-latest` (compatible hacia atrás). Fíjela en `1` sólo después de confirmar que el runner está en línea.

## Documentos relacionados

- `.github/workflows/ci.yml` — job `e2e` con `runs-on` condicional.
- `.github/workflows/e2e-self-hosted.yml` — workflow dedicado al runner auto-hospedado.
- `scripts/check-runner.ps1` — comprobación de conectividad del runner.
- `AGENTS.md` §15.1 — compuerta CI pre-MVP (lint, typecheck, test, build sólo; e2e sigue siendo opcional en pre-MVP).
- Repositorio IaC `vps-oracle` — código de aprovisionamiento de la propia VPS.