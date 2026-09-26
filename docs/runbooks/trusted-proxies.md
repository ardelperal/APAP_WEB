[← Volver a la guía del código](../CODEBASE-GUIDE.md)

# Proxies de confianza (`trusted_proxies`) y `X-Forwarded-For`

El limitador de peticiones (`app/core/rate_limit.py`) agrupa por IP de
cliente. Desde el issue #920, la cabecera `X-Forwarded-For` solo se
respeta cuando el operador declara explícitamente qué saltos de proxy son
de confianza mediante `APAP_TRUSTED_PROXIES`. Esta guía indica cuándo es
seguro activarlo, cómo configurarlo y cómo verificarlo tras el despliegue.

## Contrato operativo

- `APAP_TRUST_XFF=true` por sí solo no activa la confianza en la cabecera:
  con `APAP_TRUSTED_PROXIES` vacío (el valor por defecto) la cabecera
  nunca se consulta y la IP de cliente es la del par directo de la
  conexión TCP. Es el comportamiento seguro por omisión. En ese estado el
  arranque emite un único aviso `startup.xff_trust_noop` vía `log_safe`
  para que el operador sepa que el flag está inerte.
- `APAP_TRUSTED_PROXIES` es una lista JSON de CIDR, por ejemplo:
  `APAP_TRUSTED_PROXIES='["10.0.0.0/8","172.16.0.0/12"]'`.
- Una entrada que no sea un CIDR válido impide el arranque (validación
  fail-fast en `app/core/config.py`).
- Con proxies configurados, la resolución recorre `X-Forwarded-For` de
  derecha a izquierda saltando únicamente los saltos declarados como de
  confianza (incluido el par directo); gana el primer valor fuera de las
  redes de confianza. Si todos los candidatos son de confianza, se usa el
  par directo (fallo cerrado).
- El recorrido exige un ancla: si el par directo no es una IP parseable
  (socket unix sin info de par, o un valor como `testclient`), la cabecera
  nunca se consulta y la identidad es el par tal cual. Sin par, la
  identidad es nula.
- Si un proxy envía varias líneas `X-Forwarded-For`, todas se unen antes
  del recorrido: el salto que el proxy añadió en la segunda línea gana
  sobre el valor falsificado de la primera.
- Una entrada no parseable (basura inyectada) se salta y el recorrido
  continúa; nunca se adopta como identidad. Si el recorrido no encuentra
  ninguna IP utilizable fuera de las redes de confianza, se usa el par
  directo.
- Los pares reportados como IPv6 mapeado a IPv4 (`::ffff:a.b.c.d`) se
  normalizan a `a.b.c.d` antes de comparar con los CIDR, de modo que un
  socket IPv4-mapeado no colapse todos los clientes en un único bucket.

## Cuándo es seguro activar

Active `APAP_TRUST_XFF=true` + `APAP_TRUSTED_PROXIES` solo si se cumplen
todas las condiciones:

1. Todas las peticiones llegan a la aplicación a través de los proxies
   declarados (no hay ruta de red directa al puerto de uvicorn desde
   clientes no confiables).
2. Cada proxy de la cadena añade (append) la IP del cliente que vio al
   final de `X-Forwarded-For` — comportamiento de nginx
   (`proxy_add_x_forwarded_for`), Traefik, Caddy y los balanceadores
   habituales.
3. Los CIDR declarados cubren exclusivamente los proxies propios. Nunca
   incluya rangos que un cliente pueda ocupar.

## Topologías

**Un proxy (caso habitual: Coolify/Traefik delante de uvicorn):**

```text
cliente(203.0.113.50) → proxy(10.0.0.5) → app
X-Forwarded-For: 203.0.113.50
```

```bash
APAP_TRUST_XFF=true
APAP_TRUSTED_PROXIES='["10.0.0.0/24"]'
```

El recorrido: el par directo (10.0.0.5) es de confianza, se salta; el
siguiente valor (203.0.113.50) no lo es y se adopta como IP de cliente.

**Dos proxies en cadena:**

```text
cliente(203.0.113.50) → edge(10.0.0.5) → interno(10.0.0.6) → app
X-Forwarded-For: 203.0.113.50, 10.0.0.5
```

```bash
APAP_TRUSTED_PROXIES='["10.0.0.0/24"]'
```

Ambos saltos están en el CIDR y se saltan; gana 203.0.113.50.

**Cliente que falsifica la cabecera tras un proxy (ataque mitigado):**

```text
cliente falsificador → proxy(10.0.0.5) → app
X-Forwarded-For: 1.2.3.4 (inyectado por el cliente) + 203.0.113.50 (añadido por el proxy)
```

El proxy añade la IP real al final: `1.2.3.4, 203.0.113.50`. El recorrido
de derecha a izquierda salta 10.0.0.5 (confianza) y adopta
203.0.113.50 — el valor inyectado `1.2.3.4` queda a su izquierda y nunca
se alcanza. Sin proxies de confianza configurados, la cabecera completa
se ignora y el bucket usa el par directo, de modo que la falsificación no
cambia el bucket.

## Verificar tras el despliegue

1. **Cabecera ausente:** `curl -i https://<app>/healthz` desde fuera —
   la respuesta no debe depender de la IP falsificable.
2. **Bucket por cliente real:** efectúe 11 peticiones a `/auth/callback`
   desde una misma IP externa; la número 11 debe devolver `429`. Con la
   configuración correcta el bucket es la IP externa, no la del proxy.
3. **Falsificación ineficaz:** repita el bucle anterior añadiendo
   `-H 'X-Forwarded-For: 9.9.9.9'` — el `429` debe llegar igual (el
   bucket no cambia con cada valor falsificado). Si con `9.9.9.9` el
   límite no salta, algún salto intermedio no está declarado en
   `APAP_TRUSTED_PROXIES` o un cliente alcanza la app sin pasar por el
   proxy: corrija la configuración antes de continuar.
4. **Logs:** confirme que ningún evento de limitación registra la IP
   (requisito REQ-5/#286).

## Rollback seguro

Retire la variable `APAP_TRUSTED_PROXIES` del entorno (unset) y reinicie:
la cabecera deja de consultarse aunque `APAP_TRUST_XFF` siga en `true`.
No use `APAP_TRUSTED_PROXIES=''`: la cadena vacía no es JSON válido y la
validación de CIDR impide el arranque. El coste del rollback es agrupar
las peticiones que llegan por el proxy en un único bucket (limitación
global, no por cliente), nunca un bypass.

## Cabeceras relacionadas

`X-Request-ID` solo se honra cuando cumple el patrón `[A-Za-z0-9._-]` con
entre 1 y 128 caracteres (`app/core/request_context.py`). Los gateways
que generan identificadores con `:` o en base64 (`+`, `/`, `=`) no
encajan: la aplicación descarta el valor entrante y regenera uno propio,
que es el que llega en la respuesta y en los logs. Si su gateway
adelante `X-Request-ID`, configúrelo con el juego de caracteres aceptado.

## Referencias

- `app/core/rate_limit.py` — helpers `_resolve_client_ip`,
  `_client_ip_from_xff`, `_is_trusted_address`.
- `app/core/config.py` — campos `trust_xff` y `trusted_proxies`.
- `tests/test_trusted_proxies.py` — contrato de resolución y ataque de
  falsificación a nivel de middleware.
- `docs/runbooks/auth-cache-multi-worker.md` — limitación por proceso
  (aplica también a los buckets por IP).
