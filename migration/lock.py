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
crash, power loss), the file is stale. ``acquire_lock`` auto-recovers
only when the owner PID is verifiably dead:

1. **PID is dead**: ``psutil.pid_exists(pid)`` is ``False`` when
   ``psutil`` is available. Without ``psutil``, Windows uses the kernel
   process-query API (``OpenProcess`` + ``GetExitCodeProcess``) because
   ``os.kill(pid, 0)`` can send ``CTRL_C_EVENT`` there; POSIX keeps the
   standard ``os.kill(pid, 0)`` probe.
2. **TTL is informational**: an expired TTL does not override a live PID.
   A live migration can stall longer than TTL; overwriting its lock would
   risk split-brain writes. Manual cleanup is required for corrupt locks
   or for live-PID locks the operator has verified are safe to remove.

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
- ``LockActiveError`` (re-exported from ``migration``).
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
from typing import TYPE_CHECKING, NoReturn

# Importación tolerante: ``psutil`` es opcional (design §1.2).
# Si no está instalado, el módulo degrada gracefully — los checks
# de "process alive" caen a un fallback menos preciso (asume vivo si
# no se puede verificar) y ``check_msaccess_running`` retorna ``[]``.
try:
    import psutil as _psutil_module

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only without psutil
    _psutil_module = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

# Bind ``psutil`` a nivel módulo (además de ``_psutil_module``) para que
# ``check_msaccess_running`` y los tests que hacen
# ``monkeypatch.setattr(lock_mod, "psutil", fake, raising=True)``
# encuentren el nombre en ``sys.modules[__name__]``. Sin esto, el
# ``getattr(sys.modules[__name__], "psutil", None)`` dentro de
# ``check_msaccess_running`` retorna ``None`` y la función siempre
# devuelve ``[]`` aunque psutil esté instalado (P0 #1 bug — code review
# PR #99, fix).
psutil = _psutil_module


if TYPE_CHECKING:
    # Solo para anotaciones; el import real se hace lazy en
    # ``acquire_lock`` para evitar el ciclo
    # ``__init__`` → ``lock`` → ``__init__``.
    from migration import LockActiveError


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
         a. Si el lock es parseable Y el PID dueño está muerto
            → sobrescribir (delete + write nuevo).
         b. Si el lock es parseable Y el PID dueño está vivo
            → ``LockActiveError`` (incluso si TTL expiró).
         c. Si el lock NO es parseable (vacío o corrupto) → ``LockActiveError``.
            Nunca se auto-recupera un lock corrupto; un writer puede estar
            pausado entre os.open y fdopen por tiempo arbitrario.
      2. Si el archivo NO existe: crear nuevo.

    La creación del archivo es atómica: reclamamos directamente
    ``lock_path`` con ``O_CREAT|O_EXCL``. Un segundo acquire concurrente
    no puede crear ni sobrescribir el lock real; debe observarlo y
    responder ``LockActiveError``.

    Args:
        lock_path: ruta al lock file (convencionalmente al lado de
            ``sync_state.json``, ej: ``<migration_dir>/migration.lock``).
        ttl_seconds: TTL del lock. Default 1800s (30 min).

    Returns:
        ``LockInfo`` con el lock recién adquirido (útil para tests).

    Raises:
        LockActiveError: si el lock existe y es activo, o si el lock
            existe y es vacío/corrupto (requiere limpieza manual si no
            hay otro proceso escribiéndolo).
        OSError: si hay un error de I/O al escribir el lock.
    """
    lock_path = Path(lock_path)
    _ensure_parent_dir(lock_path)
    _check_and_clear_existing_lock(lock_path)

    # Fase 2: crear el lock nuevo.
    info = LockInfo(
        pid=os.getpid(),
        acquired_at=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
    )
    return _claim_new_lock(lock_path, info)


def _ensure_parent_dir(lock_path: Path) -> None:
    """Crea el directorio padre de ``lock_path`` si no existe.

    Factorizado desde ``acquire_lock`` para bajar CC; la rama del
    directorio padre no es trivial y merece un test dedicado porque
    ``apply`` confía en que el lock file se pueda crear en un
    directorio nuevo (p.ej. primer run post-deploy).
    """
    parent = lock_path.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def _check_and_clear_existing_lock(lock_path: Path) -> None:
    """Fase 1 de ``acquire_lock``: evalúa y limpia el lock preexistente.

    Cuatro resultados posibles:
      - No hay lock file → no-op, return.
      - Lock parseable y dueño vivo → ``LockActiveError`` (bloquea).
      - Lock parseable y dueño muerto (stale) → unlink + return.
      - Lock corrupto/vacío → ``LockActiveError`` (nunca se auto-recupera).

    Raises:
        LockActiveError: si el lock está activo o si está corrupto/vacío
            (un writer in-flight puede estar pausado entre ``os.open`` y
            ``f.write`` por tiempo arbitrario; unlink+acquire por otro
            proceso rompería el contrato — ambos retornarían success).
    """
    from migration import LockActiveError

    existing = _read_lock_unverified(lock_path)
    if existing is None:
        # No parseable: o no existe o está corrupto/vacío.
        if lock_path.exists():
            # Archivo existe pero no se pudo parsear. Nunca se
            # auto-recupera: podría ser un writer pausado a mitad
            # de escritura.
            raise LockActiveError(
                "Lock file exists but is empty or corrupt (unparseable). "
                "Another process may be acquiring it. "
                "Manually remove the lock file if no other process is running."
            ) from None
        return
    if not _is_lock_stale(existing):
        # Lock activo: PID vivo, incluso si TTL expiró.
        raise LockActiveError(
            f"Migration lock is active (pid={existing.pid}, "
            f"acquired_at={existing.acquired_at.isoformat()}, "
            f"ttl={existing.ttl_seconds}s)"
        )
    # Parseable y stale: unlink con race handling.
    _unlink_stale_lock(lock_path)


def _unlink_stale_lock(lock_path: Path) -> None:
    """Unlink de un lock stale, tolerando que otro proceso lo borre antes."""
    try:
        lock_path.unlink()
    except FileNotFoundError:
        # Otro proceso pudo haberlo borrado entre read y unlink.
        # Race aceptable; seguimos.
        pass


def _claim_new_lock(lock_path: Path, info: LockInfo) -> LockInfo:
    """Fase 2 de ``acquire_lock``: crea atómicamente el lock y lo escribe.

    Usa ``O_CREAT|O_EXCL|O_WRONLY`` sobre ``lock_path`` (no un ``.tmp``)
    para garantizar que dos acquires concurrentes sobre un lock
    inexistente producen un ganador y un ``LockActiveError``. Si
    ``os.open`` falla con ``FileExistsError``, ``_raise_after_concurrent_acquire``
    evalúa el estado del archivo y levanta el error adecuado.

    Si la escritura del JSON falla (disco lleno, proceso matado),
    el lock creado se borra para no dejar basura que confunda el
    próximo acquire.

    Raises:
        LockActiveError: si otro acquire concurrente ganó el slot.
    """
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        _raise_after_concurrent_acquire(lock_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(info.to_json())
    except BaseException:
        # Si write falló (disco lleno, proceso matado), limpia el lock
        # para no dejar basura que confunda el próximo acquire.
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass
        raise
    return info


def _raise_after_concurrent_acquire(lock_path: Path) -> NoReturn:
    """Levanta ``LockActiveError`` cuando un acquire concurrente ganó el slot.

    Re-lee el lock file para construir un error útil cuando sea posible.
    Si el ganador todavía está escribiendo y el JSON no es parseable,
    preservamos igualmente el contrato: el segundo caller recibe
    ``LockActiveError``, nunca un error de I/O o JSON intermedio.
    """
    from migration import LockActiveError

    existing = _read_lock_unverified(lock_path)
    if existing is not None and not _is_lock_stale(existing):
        raise LockActiveError(
            f"Migration lock is active (pid={existing.pid}, "
            f"acquired_at={existing.acquired_at.isoformat()}, "
            f"ttl={existing.ttl_seconds}s)"
        ) from None
    # Lock corrupto/mid-write o stale justo en la ventana de carrera:
    # para el segundo acquire concurrente seguimos devolviendo
    # LockActiveError. Un futuro retry podrá evaluar staleness con el
    # archivo ya estable.
    raise LockActiveError(
        "Concurrent acquire is in flight; lock file is not stable yet. "
        "Retry shortly."
    ) from None


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

    Un lock parseable solo se considera stale cuando el proceso dueño
    (PID) ya no está vivo (``_is_process_alive(lock.pid) == False``).
    Si el PID es vivo, el lock permanece activo aunque el TTL haya
    expirado — un proceso vivo puede haber stalled por razones
    legítimas (ej: migración larga, operador en debugging con breakpoint).

    Si no podemos verificar la liveness del PID (fallback conservador
    retorna ``True``), NO sobrescribimos: es mejor bloquear de más que
    provocar una migración split-brain.
    """
    if not _is_process_alive(lock.pid):
        return True
    # PID vivo — lock NO es stale aunque TTL haya expirado.
    return False


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

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()  # type: ignore[attr-defined]
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

    Raises:
        MsAccessPreflightUnavailableError: when ``psutil`` is missing
            or ``process_iter`` raises during iteration. The apply
            pipeline fails closed (PR3 verification remediation, per
            user directive 2026-07-11): better to abort than to claim
            "no MSACCESS live" while the check was unable to actually
            look. The CLI converts this exception to exit 5 with
            reason ``msaccess_preflight_unavailable``. The apply
            layer emits ``log_safe("apply.preflight_unavailable",
            reason=<cat>)`` for audit; the log event carries ONLY the
            categorical reason — no PIDs, no error strings.

    El matching es case-insensitive (``MSACCESS.EXE`` vs
    ``msaccess.exe`` vs ``MSAccess.exe``) porque el nombre exacto
    depende del OS y la convención.
    """
    # Lazy import to break the ``__init__`` ↔ ``lock`` cycle. The
    # exception type lives in ``migration.__init__`` so the public
    # surface (``from migration import MsAccessPreflightUnavailableError``)
    # is stable; the body of this function imports it on first call.
    # Búsqueda dinámica del módulo ``psutil`` para que tests que
    # hacen ``monkeypatch.setattr(lock_mod, "psutil", fake)`` surtan
    # efecto sin re-importar.
    import sys

    from migration import MsAccessPreflightUnavailableError

    psutil_obj = getattr(sys.modules[__name__], "psutil", None)
    available = getattr(sys.modules[__name__], "_PSUTIL_AVAILABLE", False)
    if not available or psutil_obj is None:
        # Fail closed: do NOT silently claim "no MSACCESS live" when
        # the check was unable to run. ``psutil`` is a hard
        # requirement on operator boxes (the runbook documents this).
        raise MsAccessPreflightUnavailableError(
            reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
        )
    pids: list[int] = []
    try:
        attrs = ["pid", "name"]
        for proc in psutil_obj.process_iter(attrs):
            # psutil 5.9+ expone ``proc.info`` como un dict-like
            # ``Mapping`` con las keys pedidas en ``attrs``. La
            # firma exacta varía entre versiones (algunas
            # requieren ``proc.info(attrs)``, otras tienen
            # ``proc.info`` como atributo directo); soportamos
            # ambos formatos para mantener compatibilidad con
            # mocks de tests y versiones más viejas.
            try:
                info_obj = proc.info
                if callable(info_obj):
                    info_dict = info_obj(attrs)
                else:
                    info_dict = info_obj
                name = (info_dict.get("name") or "").upper()
            except Exception:  # proceso murió durante iter
                name = None
            if name == "MSACCESS.EXE":
                pid = info_dict.get("pid")
                if isinstance(pid, int):
                    pids.append(pid)
    except MsAccessPreflightUnavailableError:
        # Re-raise the typed exception unchanged (defensive: in case a
        # future refactor wraps the iteration loop).
        raise
    except Exception as exc:  # noqa: BLE001 — psutil.iter puede fallar por permisos
        # Fail closed: a transient psutil / OS error during iteration
        # is the same risk class as ``psutil`` being missing. Better
        # to abort than to claim "no MSACCESS live".
        raise MsAccessPreflightUnavailableError(
            reason=(
                MsAccessPreflightUnavailableError.REASON_PROCESS_ITERATION_FAILED
            )
        ) from exc
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
