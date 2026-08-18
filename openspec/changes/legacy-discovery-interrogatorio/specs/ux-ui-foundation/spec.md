# Spec: FOUNDATION — UX/UI Base: Design System y Componentes (issue #6, task 3.11)

## Context

Issue #6. Definir la base UX/UI: design tokens (colores, tipografía, spacing),
componentes reutilizables (botones, inputs, cards, modals), y layout base de la
navegación. Esto es prerequisite para todas las features de UI.

## Current state on main@0ab533d

**Ya existe:**
- `docs/design-tokens-apap-actual.md` — tokens heredados del legacy como referencia.
- `docs/architecture/decisiones-proyecto.md` §D-11 ("No clonar la UX del legacy") y §D-12
  ("Design system reutilizable").
- Tailwind v4 configurado en el proyecto.
- `base.html` con layout básico de navegación.

**Falta:**
- Design tokens oficiales del nuevo sistema (reemplazando los heredados del legacy).
- Componentes reutilizables Jinja2 (para HTML server-rendered con HTMX).
- Nav principal con enlaces a todas las secciones.
- Responsive layout (mobile + desktop).

**GAP:** El skill `frontend-design` está disponible para aplicar Telefónica Brand
Factory / Mística al proyecto. No está claro si se usa el skill o se crean
tokens nuevos. Necesita decisión de producto.

## Required contract

### GAP: Design system approach not defined

> **[GAP: needs product decision before implementation]**
> Dos opciones identificadas:
> 1. **Telefónica Mística design system**: usar el skill `telefonica-brand-design`
>    para aplicar Mística/Telefónica Brand Factory tokens + componentes.
>    Pros: design system oficial de la marca, mantenido por Telefónica.
>    Cons: podría ser overkill para una protectora pequeña. <!-- alantyle-ignore:ALAN004 -->
> 2. **Tokens propios + componentes custom**: crear design tokens propios
>    basados en los del legacy (`docs/design-tokens-apap-actual.md`) modernizados.
>
> Necesita decisión del usuario/mantenedor antes de proceder.

### Si se elige opción 1 (Mística)

Design tokens Mística para este proyecto (pendiente de decisión):

- **Brand color**: `#0A91EB` (APAP primary blue) — confirmado por el mockup de login.
- **Secondary**: `#076FB8` (gradient).
- **Neutral**: `#4A4A4A` (text), `#F5F5F5` (background).

Componentes Mística: buttons, inputs, cards, modals, breadcrumbs, pagination.

### Estructura de templates

```
templates/
  base.html                    # layout base con nav + flash messages
  components/
    button.html               # <button> con variants: primary, secondary, danger
    input.html                # <input> con label, error, help text
    card.html                 # <div> card con header/body/footer
    modal.html                # modal dialog con close
    table.html               # <table> con sorting
    pagination.html           # paginator
    badge.html               # status badges (chip color-coded)
    alert.html               # flash messages / toasts
  partials/
    animal_card.html
    voluntario_card.html
    ...
```

### Nav principal

```html
<!-- Desktop: horizontal -->
<nav class="hidden md:flex gap-4">
  <a href="/animales">Animales</a>
  <a href="/voluntarios">Voluntarios</a>
  <a href="/entradas">Entradas</a>
  <a href="/acogidas">Acogidas</a>
  <a href="/adopciones">Adopciones</a>
  <a href="/sanidad">Sanidad</a>
  <a href="/tareas">Tareas</a>
  <a href="/reportes">Informes</a>
  <a href="/admin">Admin</a>
</nav>

<!-- Mobile: hamburger drawer -->
```

### Responsive breakpoints

- Mobile: < 768px (hamburger menu, stacked layouts)
- Tablet: 768px – 1024px (2-column layouts)
- Desktop: > 1024px (full layout)

## Dependencies

- Ninguna — es foundation pura.

## Acceptance criteria

1. `base.html` tiene nav responsive (mobile hamburger + desktop horizontal).
2. Design tokens definidos en CSS custom properties (Tailwind config o CSS variables).
3. Componentes base (`button`, `input`, `card`, `modal`) disponibles como Jinja2
   includes en `templates/components/`.
4. Flash messages (success/error/warning) renderizan en `base.html`.
5. Los templates de features existentes (`animales/list.html`, etc.) se refactorizan
   para usar los componentes base.
6. No se copian estilos inline de los mockups legacy — todo va a CSS/Tailwind.
7. El color primary de la protectora (`#0A91EB`) se usa consistentemente.

## Out-of-scope

- Animaciones avanzadas o micro-interacciones (hover effects simples sí).
- Dark mode.
- Tema por usuario.
- Búsqueda global (feature separada).
