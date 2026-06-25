"""Lock file for migration run concurrency (LIFECYCLE-03 / migration-01).

This module provides a **PID-based file lock** that prevents two
``apap-migrate`` runs from executing concurrently (regla #13474 v2:
función de migración atómica). The lock file lives next to
``sync_state.json`` and contains:

```json
{
  "pid": 12345,
  "acquired_at": "2026-06-21T12:34:56+00:00",
  "ttl_seconds": 1800
}
```

**Stale recovery** (the killer feature):

If the holding process died without releasing the lock (kill -9, OOM,
crash, power loss), the file is stale. ``acquire_lock`` detects this
two ways and overwrites the lock:

1. **PID is dead**: ``psutil.pid_exists(pid)`` is ``False`` when
   ``psutil`` is available. Without ``psutil``, Windows uses the kernel
   process-query API (``OpenProcess`` + ``GetExitCodeProcess``) because
   ``os.kill(pid, 0)`` can send ``CTRL_C_EVENT`` there; POSIX keeps the
   standard ``os.kill(pid, 0)`` probe.
2. **TTL expired**: ``now - acquired_at > ttl_seconds``. Default TTL
   is 30 minutes (1800s) — generous enough for a full sync (design §12
   estimates 10-15 min) but short enough that a dead run doesn't
   block the next day.

**Pre-flight MSACCESS check** (design §14):

Before writing to a legacy ``.accdb``, the operator MUST close Access
(múltiples writers corrompen el archivo binario). ``check_msaccess_running``
returns the list of PIDs whose process name is ``MSACCESS.EXE`` so the
CLI can warn or abort. ``psutil`` is a **soft dependency** — if not
installed, the check returns ``[]`` and the migration continues (with
a warning log). This avoids breaking the module in minimal
environments where ``psutil`` isn't pulled in.

**Public API contract** (kept stable for PR 5/6 applier):

- ``LockInfo`` dataclass.
- ``acquire_lock(path, ttl_seconds=1800)``.
- ``release_lock(path)``.
- ``check_lock(path) -> LockInfo | None``.
- ``LockActiveError`` (re-exported from ``app.core.migration``).
- ``check_msaccess_running() -> list[int]``.
"""

from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Importación tolerante: ``psutil`` es opcional (design §1.2).
# Si no está instalado, el módulo degrada gracefully — los checks
# de "process alive" caen a un fallback menos preciso (asume vivo si
# no se puede verificar) y ``check_msaccess_running`` retorna ``[]``.
try:
    import psutil as _psutil_module

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only without psutil
    _psutil_module = None
    _PSUTIL_AVAILABLE = False

# Bind ``psutil`` a nivel módulo (además de ``_psutil_module``) para que
# ``check_msaccess_running`` y los tests que hacen
# ``monkeypatch.setattr(lock_mod, "psutil", fake, raising=True)``
# encuentren el nombre en ``sys.modules[__name__]``. Sin esto, el
# ``getattr(sys.modules[__name__], "psutil", None)`` dentro de
# ``check_msaccess_running`` retorna ``None`` y la función siempre
# devuelve ``[]`` aunque psutil esté instalado (P0 #1 bug — code review
# PR #99, fix).
psutil = _psutil_module  # type: ignore[assignment]


if TYPE_CHECKING:
    # Solo para anotaciones; el import real se hace lazy en
    # ``acquire_lock`` para evitar el ciclo
    # ``__init__`` → ``lock`` → ``__init__``.
    from app.core.migration import LockActiveError


DEFAULT_TTL_SECONDS: int = 1800
"""TTL default del lock: 30 minutos (design §16).

Suficiente para un full sync (10-15 min estimados, design §12) pero
lo bastante corto para no bloquear runs del día siguiente si el
proceso murió a mitad del sync anterior.
"""


@dataclass(frozen=True)
class LockInfo:
    """Contenido del lock file.

    ``pid`` es el PID del proceso que posee el lock. ``acquired_at``
    es el timestamp de cuándo se adquirió (UTC). ``ttl_seconds`` es
    el tiempo después del cual el lock se considera stale (default
    :data:`DEFAULT_TTL_SECONDS`).

    El dataclass es ``frozen=True`` para que dos ``acquire_lock``
    concurrentes que leen el mismo lock no generen un estado mixto
    inconsistente (uno modifica mientras el otro lee).
    """

    pid: int
    acquired_at: datetime
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    def to_json(self) -> str:
        """Serializa a JSON UTF-8 (forma canónica en disco)."""
        return json.dumps(
            {
                "pid": self.pid,
                "acquired_at": self.acquired_at.isoformat(),
                "ttl_seconds": self.ttl_seconds,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> LockInfo:
        """Deserializa desde un JSON string.

        Raises:
            ValueError: si el JSON no tiene la forma esperada.
        """
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Lock file root must be a JSON object, got {type(data).__name__}")
        pid = data.get("pid")
        acquired_at_raw = data.get("acquired_at")
        ttl = data.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        if not isinstance(pid, int):
            raise ValueError(f"Lock file 'pid' must be an integer, got {type(pid).__name__}")
        if not isinstance(acquired_at_raw, str):
            raise ValueError(
                f"Lock file 'acquired_at' must be a string, got {type(acquired_at_raw).__name__}"
            )
        try:
            acquired_at = datetime.fromisoformat(acquired_at_raw)
        except ValueError as exc:
            raise ValueError(
                f"Lock file 'acquired_at' is not ISO-8601: {acquired_at_raw!r}"
            ) from exc
        if not isinstance(ttl, int):
            raise ValueError(
                f"Lock file 'ttl_seconds' must be an integer, got {type(ttl).__name__}"
            )
        if acquired_at.tzinfo is None:
            acquired_at = acquired_at.replace(tzinfo=UTC)
        return cls(pid=pid, acquired_at=acquired_at, ttl_seconds=ttl)


# --- Public API: lock acquisition & release --------------------------------


def acquire_lock(
    lock_path: Path | str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> LockInfo:
    """Adquiere el lock en ``lock_path`` para el proceso actual.

    Algoritmo:
      1. Si el archivo existe: leerlo.
         a. Si el lock NO está stale (PID vivo + TTL vigente) →
            ``LockActiveError``.
         b. Si está stale (PID muerto o TTL expirado) → sobrescribir
            (delete + write nuevo).
      2. Si el archivo NO existe: crear nuevo.

    La creación del archivo es **atómica con sobrescritura segura**:
    escribimos a ``{lock_path}.tmp`` + ``os.replace``. ``os.replace``
    es atómico en Windows + POSIX (mismo filesystem) y sobrescribe
    el destino sin race condition con lectores.

    Args:
        lock_path: ruta al lock file (convencionalmente al lado de
            ``sync_state.json``, ej: ``<migration_dir>/migration.lock``).
        ttl_seconds: TTL del lock. Default 1800s (30 min).

    Returns:
        ``LockInfo`` con el lock recién adquirido (útil para tests).

    Raises:
        LockActiveError: si el lock existe y NO está stale.
        OSError: si hay un error de I/O al escribir el lock.
    """
    # Importación lazy para romper el ciclo ``__init__`` → ``lock``.
    from app.core.migration import LockActiveError

    lock_path = Path(lock_path)
    parent = lock_path.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    # Fase 1: si el lock existe, verificar staleness.
    if lock_path.exists():
        existing = _read_lock_unverified(lock_path)
        if existing is not None and not _is_lock_stale(existing):
            raise LockActiveError(
                f"Migration lock is active (pid={existing.pid}, "
                f"acquired_at={existing.acquired_at.isoformat()}, "
                f"ttl={existing.ttl_seconds}s)"
            )
        # Lock stale o corrupto → sobrescribir.
        try:
            lock_path.unlink()
        except FileNotFoundError:
            # Otro proceso pudo haberlo borrado entre read y unlink.
            # Race aceptable; seguimos.
            pass

    # Fase 2: crear el lock nuevo.
    info = LockInfo(
        pid=os.getpid(),
        acquired_at=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
    )

    # Escritura atómica (claim tmp + replace) para evitar un lock
    # corrupto en disco si el proceso muere a mitad (regla #13474 v2).
    # Usamos ``os.open(O_CREAT|O_EXCL|O_WRONLY)`` para que solo UN hilo
    # gane el slot del archivo tmp cuando dos ``acquire_lock`` corren
    # concurrentemente sobre un lock inexistente. Sin O_EXCL, ambos
    # hilos ven ``not exists``, ambos hacen ``write_text`` al mismo
    # ``.tmp`` y el segundo writer se lleva un ``PermissionError:
    # [WinError 32]`` en Windows (P0 #2 bug — code review PR #99).
    tmp_path = lock_path.with_suffix(lock_path.suffix + ".tmp")
    try:
        fd = os.open(tmp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Otro ``acquire_lock`` concurrente ganó el slot del tmp. Re-leemos
        # el lock file real: si ya está visible (el contender terminó su
        # ``os.replace``), evaluamos staleness y levantamos LockActiveError
        # según corresponda. Si NO está visible todavía (contender murió
        # mid-write o el race window es estrecho), también levantamos
        # LockActiveError con un mensaje claro para que el caller pueda
        # reintentar limpiamente — nunca propagamos el PermissionError
        # raw que era el comportamiento pre-fix.
        existing = _read_lock_unverified(lock_path)
        if existing is not None and not _is_lock_stale(existing):
            raise LockActiveError(
                f"Migration lock is active (pid={existing.pid}, "
                f"acquired_at={existing.acquired_at.isoformat()}, "
                f"ttl={existing.ttl_seconds}s)"
            ) from None
        # Lock no visible todavía (contender mid-write) o stale → el
        # contrato del docstring es "one success, one LockActiveError",
        # así que siempre surface LockActiveError para preservar el
        # contrato (nunca PermissionError).
        raise LockActiveError(
            "Concurrent acquire is in flight; lock file not yet visible "
            "or contender's lock is stale. Retry shortly."
        ) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(info.to_json())
    except BaseException:
        # Si write falló (disco lleno, proceso matado), limpia el tmp
        # para no dejar basura que confunda el próximo acquire.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    os.replace(tmp_path, lock_path)
    return info


def release_lock(lock_path: Path | str) -> None:
    """Libera el lock en ``lock_path``.

    Idempotente: si el archivo no existe (por ejemplo, ya fue
    liberado por otro path), NO levanta excepción. Solo intentamos
    borrar — un fallo de permisos propaga ``PermissionError``.
    """
    lock_path = Path(lock_path)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def check_lock(lock_path: Path | str) -> LockInfo | None:
    """Lee el lock file sin adquirirlo (read-only check).

    Retorna ``None`` si el archivo no existe o está corrupto (NO
    raise — el caller decide si tratar un lock corrupto como
    ``LockActiveError`` o como stale). Retorna el ``LockInfo`` si es
    parseable, **incluso si está stale** (el caller decide).

    Args:
        lock_path: ruta al lock file.

    Returns:
        ``LockInfo`` parseado, o ``None``.
    """
    lock_path = Path(lock_path)
    return _read_lock_unverified(lock_path)


# --- Internal: stale detection ---------------------------------------------


def _is_lock_stale(lock: LockInfo) -> bool:
    """True si el lock debe considerarse stale y sobrescribirse.

    Una de dos condiciones basta:
      1. El PID ya no existe (``_is_process_alive(lock.pid) == False``).
      2. El TTL expiró (``now - lock.acquired_at > lock.ttl_seconds``).
    """
    if not _is_process_alive(lock.pid):
        return True
    now = datetime.now(UTC)
    elapsed = (now - lock.acquired_at).total_seconds()
    return elapsed > lock.ttl_seconds


def _is_process_alive(pid: int) -> bool:
    """True si el proceso ``pid`` está corriendo.

    Usa ``psutil.pid_exists`` si está disponible (más fiable: no
    requiere permisos, no tiene side effects). Si ``psutil`` no
    está instalado, Windows usa ``OpenProcess`` +
    ``GetExitCodeProcess`` para evitar ``os.kill(pid, 0)`` porque en
    Windows señal ``0`` puede interrumpir el proceso actual. POSIX cae
    a ``os.kill(pid, 0)`` que es la API estándar. Si no podemos verificar
    por permisos o errores inesperados, asumimos vivo para ser
    conservadores (mejor bloquear de más que corromper el estado).
    """
    if _PSUTIL_AVAILABLE:
        try:
            return bool(_psutil_module.pid_exists(pid))
        except Exception:  # noqa: BLE001 — psutil puede fallar en algunos OS
            return True  # fail-safe: asumir vivo si no podemos verificar
    if os.name == "nt":
        return _is_process_alive_windows(pid)
    # Fallback sin psutil: os.kill(pid, 0) no mata, solo verifica.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # El proceso existe pero no tenemos permiso para señalarlo.
        # Lo tratamos como vivo (conservador — NO overwrite).
        return True
    except OSError:
        # Cualquier otro error (Windows sin PROCESS_QUERY_LIMITED_INFORMATION,
        # etc.) → fail-safe.
        return True
    return True


def _is_process_alive_windows(pid: int) -> bool:
    """Windows PID liveness check used when psutil is unavailable.

    ``os.kill(pid, 0)`` is a POSIX liveness probe, but on Windows signal
    ``0`` is ``CTRL_C_EVENT``. Using it as a probe can interrupt the current
    test run, so we use the kernel process query API instead.
    """
    if pid <= 0:
        return False

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        if error == error_access_denied:
            return True
        return True

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _read_lock_unverified(lock_path: Path) -> LockInfo | None:
    """Lee el lock file. ``None`` si no existe o es corrupto."""
    if not lock_path.exists():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return LockInfo.from_json(raw)
    except (ValueError, json.JSONDecodeError):
        return None


# --- Public API: MSACCESS pre-flight ---------------------------------------


def check_msaccess_running() -> list[int]:
    """Retorna la lista de PIDs cuyo nombre de proceso es ``MSACCESS.EXE``.

    Si ``psutil`` no está disponible (dependencia soft, design §1.2),
    retorna ``[]`` — el pre-flight es no-op y la migración puede
    continuar. El CLI loggea un warning en ese caso para que el
    operador cierre Access manualmente.

    El matching es case-insensitive (``MSACCESS.EXE`` vs
    ``msaccess.exe`` vs ``MSAccess.exe``) porque el nombre exacto
    depende del OS y la convención.
    """
    # Búsqueda dinámica del módulo ``psutil`` para que tests que
    # hacen ``monkeypatch.setattr(lock_mod, "psutil", fake)`` surtan
    # efecto sin re-importar.
    import sys

    psutil_obj = getattr(sys.modules[__name__], "psutil", None)
    available = getattr(sys.modules[__name__], "_PSUTIL_AVAILABLE", False)
    if not available or psutil_obj is None:
        return []
    pids: list[int] = []
    try:
        attrs = ["pid", "name"]
        for proc in psutil_obj.process_iter(attrs):
            try:
                # psutil 5.9+ expone ``proc.info`` como un dict-like
                # ``Mapping`` con las keys pedidas en ``attrs``. La
                # firma exacta varía entre versiones (algunas
                # requieren ``proc.info(attrs)``, otras tienen
                # ``proc.info`` como atributo directo); soportamos
                # ambos formatos para mantener compatibilidad con
                # mocks de tests y versiones más viejas.
                info_obj = proc.info
                if callable(info_obj):
                    info_dict = info_obj(attrs)
                else:
                    info_dict = info_obj
                name = (info_dict.get("name") or "").upper()
            except Exception:  # noqa: BLE001 — proceso murió durante iter
                continue
            if name == "MSACCESS.EXE":
                pid = info_dict.get("pid")
                if isinstance(pid, int):
                    pids.append(pid)
    except Exception:  # noqa: BLE001 — psutil.iter puede fallar por permisos
        return pids
    return pids
    return pids


# Sentinel usado por tests para monkeypatching; declarado a nivel
# módulo para que ``monkeypatch.setattr(lock_mod, "_PSUTIL_AVAILABLE", ...)``
# tenga un target estable (ver tests/test_migration.py::TestLock).
_PSUTIL_AVAILABLE = _PSUTIL_AVAILABLE


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "LockActiveError",
    "LockInfo",
    "acquire_lock",
    "check_lock",
    "check_msaccess_running",
    "release_lock",
]
