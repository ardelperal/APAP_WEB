# Exploración: Base UX/UI de APAP

### Estado actual
- La app ya es server-rendered (FastAPI + Jinja2 + Tailwind) y el home se renderiza desde `app/templates/index.html`.
- La cabecera común está en `app/templates/base.html`: navegación superior, login/logout y pie de página.
- El home actual ya funciona como panel operativo: hero, 10 tarjetas de pendientes y 3 accesos rápidos.
- El texto visible evita términos internos/legacy; hay tests que lo fuerzan.
- Solo existen cuatro rutas de dominio montadas hoy: `animales`, `entradas`, `cesiones` y `voluntarios`.
- `docs/architecture/decisiones-proyecto.md` sí existe y ya fija la base de producto/UX: APAP_WEB es un producto standalone, el home es una bandeja de pendientes, el dominio pivota sobre Animal, el idioma visible es castellano de España y la UX no debe clonar el legacy.

### Áreas afectadas
- `app/main.py` — composición del home, navegación y lista de tarjetas/accesos.
- `app/templates/base.html` — shell global, cabecera, navegación y pie.
- `app/templates/index.html` — home operativo y estados visuales.
- `app/templates/login.html` / `app/templates/unauthorized.html` / `app/templates/admin.html` — coherencia visual del sistema.
- `app/static/css/output.css` — tokens visuales y base tipográfica actual.
- `tests/test_pages.py` — contract tests de copy, dashboard y restricciones de lenguaje.
- `docs/roadmap.md`, `docs/architecture/decisiones-proyecto.md`, `docs/discovery/*`, `docs/legacy-initial-dashboard.md`, `docs/legacy-volunteer-roles.md` — contexto de negocio, decisiones vigentes y referencias visuales.

### Enfoques
1. **Shell incremental con IA semántica de producto** — definir un sistema visual propio y extender la cáscara actual sin tocar lógica de negocio.
   - Pros: menor riesgo; encaja con la arquitectura actual; respeta el trabajo ya verificado.
   - Cons: la navegación completa dependerá de módulos aún no implementados.
   - Esfuerzo: Medio.

2. **Recreación cercana del dashboard legacy** — copiar patrones visuales y de navegación del Access original.
   - Pros: rápida referencia para operativa y estados pendientes.
   - Cons: choca con la decisión de no clonar la UX legacy; alto riesgo de copiar copy/jerarquías internas.
   - Esfuerzo: Medio.

3. **Sistema de diseño primero, contenido después** — cerrar tokens, jerarquía visual y estados (normal/pending/critical/empty) antes de fijar la navegación completa.
   - Pros: deja una base sólida y escalable; ayuda a que el producto parezca final y autónomo.
   - Cons: requiere más definición inicial; la IA quedará algo abstracta hasta que existan más módulos.
   - Esfuerzo: Medio/Alto.

### Recomendación
Tomar el **enfoque 1 combinado con 3**: construir una base de diseño propia, pero aplicada de forma incremental al shell actual. Eso permite fijar ya la identidad visual, el home operativo y las reglas de estados, sin depender de que existan todavía todos los módulos de negocio.

**Decisiones productivas ya claras:**
- No usar lenguaje interno, migración, stack ni referencias al origen Access.
- El home debe ser una bandeja operativa, no una portada informativa.
- La navegación debe hablar en términos de áreas de trabajo, no de implementación.
- Los estados visuales deben distinguir normal, pendiente, crítico y vacío.

**Preguntas abiertas que conviene cerrar en `sdd-propose`:**
- ¿La navegación mostrará áreas futuras como enlaces activos, deshabilitados o solo como agrupaciones?
- ¿El dashboard debe priorizar tareas por severidad, por frecuencia de uso o por flujo operativo?
- ¿Qué grado de fidelidad semántica se conserva del dashboard legacy (tarjetas/pendientes) sin copiar su numeración ni su jerga?

### Riesgos
- La superficie de rutas actual es pequeña; parte de la navegación solicitada aún no tiene destino real.
- Los tests ya bloquean copy interno y lenguaje técnico; cualquier rediseño debe respetar esos contratos.
- Si se imita demasiado el legacy, se puede perder la identidad de producto que la issue pide.

### Listo para propuesta
Sí. El siguiente paso recomendado es `sdd-propose` para cerrar alcance, jerarquía visual, navegación y contrato de estados antes de diseñar tareas.
