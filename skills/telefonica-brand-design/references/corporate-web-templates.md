# Corporate website templates — Telefónica / Brand Factory

Use this reference when building a static HTML/CSS corporate website, landing page, or marketing page that cannot use `@telefonica/mistica`. This file provides copy-paste page-level patterns that implement the Telefónica brand system.

All patterns assume the CSS variables defined in `brand-guidelines.md` are already loaded. Import order: reset → brand-guidelines tokens → this file's patterns.

---

## HTML boilerplate

```html
<!DOCTYPE html>
<html lang="es" dir="ltr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="[Descripción breve de la página, máx. 160 caracteres]" />
  <title>[Título de la página] | Telefónica</title>

  <!-- Preconnect for performance -->
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />

  <!-- Telefonica Sans cannot be embedded; fall back to system font stack -->
  <style>
    :root {
      --tf-font-family: "Telefonica Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    }
  </style>

  <!-- Design tokens (import brand-guidelines.md variables here) -->
  <link rel="stylesheet" href="/css/tokens.css" />
  <!-- Page styles -->
  <link rel="stylesheet" href="/css/main.css" />

  <!-- Favicon -->
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</head>
<body>

  <!-- Skip navigation (accessibility) -->
  <a href="#main-content" class="tf-skip-link">Saltar al contenido</a>

  <!-- HEADER ──────────────────────────────── -->
  <header class="tf-header" role="banner">
    <div class="tf-container">
      <nav class="tf-nav" aria-label="Navegación principal">

        <a href="/" class="tf-nav__logo" aria-label="Telefónica — Inicio">
          <!--
            PLACEHOLDER: Replace with approved Telefónica logo from Brand Factory.
            In React, use: <TelefonicaLogo size={32} type="imagotype" /> from @telefonica/mistica.
            Do NOT recreate, trace, or extract the logo manually.
          -->
          <img src="/img/logo-telefonica.svg" alt="Telefónica" width="130" height="32" />
        </a>

        <!-- Desktop links -->
        <ul class="tf-nav__links" role="list">
          <li><a href="/empresas"     class="tf-nav__link">Empresas</a></li>
          <li><a href="/particulares" class="tf-nav__link">Particulares</a></li>
          <li><a href="/innovacion"   class="tf-nav__link">Innovación</a></li>
          <li><a href="/sostenibilidad" class="tf-nav__link">Sostenibilidad</a></li>
          <li><a href="/sobre-nosotros" class="tf-nav__link">Sobre nosotros</a></li>
        </ul>

        <!-- Desktop CTA -->
        <div class="tf-nav__cta">
          <a href="/contacto" class="tf-button tf-button--secondary">Contactar</a>
          <a href="/area-cliente" class="tf-button tf-button--primary">Área cliente</a>
        </div>

        <!-- Mobile menu toggle -->
        <button
          class="tf-nav__burger"
          aria-label="Abrir menú"
          aria-expanded="false"
          aria-controls="mobile-menu"
          onclick="toggleMenu(this)"
        >
          <span class="tf-nav__burger-line"></span>
          <span class="tf-nav__burger-line"></span>
          <span class="tf-nav__burger-line"></span>
        </button>

      </nav>
    </div>

    <!-- Mobile menu -->
    <div id="mobile-menu" class="tf-nav__mobile" role="dialog" aria-label="Menú de navegación">
      <a href="/empresas"      class="tf-nav__link">Empresas</a>
      <a href="/particulares"  class="tf-nav__link">Particulares</a>
      <a href="/innovacion"    class="tf-nav__link">Innovación</a>
      <a href="/sostenibilidad" class="tf-nav__link">Sostenibilidad</a>
      <a href="/sobre-nosotros" class="tf-nav__link">Sobre nosotros</a>
      <div style="display:flex; gap: var(--space-3); margin-top: var(--space-4);">
        <a href="/contacto"    class="tf-button tf-button--secondary" style="flex:1; justify-content:center;">Contactar</a>
        <a href="/area-cliente" class="tf-button tf-button--primary"  style="flex:1; justify-content:center;">Área cliente</a>
      </div>
    </div>
  </header>

  <!-- MAIN CONTENT ─────────────────────────── -->
  <main id="main-content">

    <!-- HERO ─────────────────────── -->
    <section class="tf-hero" aria-labelledby="hero-title">
      <div class="tf-container">
        <div class="tf-hero__inner">
          <div class="tf-hero__content">
            <p class="tf-hero__eyebrow">Conectamos el futuro</p>
            <h1 id="hero-title" class="tf-hero__title">
              La tecnología que transforma vidas
            </h1>
            <p class="tf-hero__body">
              Llevamos más de 40 años construyendo la red que conecta a millones
              de personas y empresas en todo el mundo.
            </p>
            <div class="tf-hero__actions">
              <a href="/empresas"   class="tf-button tf-button--primary tf-button--lg">Descubrir soluciones</a>
              <a href="/nosotros"   class="tf-button tf-button--tertiary tf-button--lg">Quiénes somos</a>
            </div>
          </div>
          <div class="tf-hero__media">
            <img
              src="/img/hero-main.jpg"
              alt="Persona usando tecnología Telefónica en ciudad conectada"
              width="640" height="480"
              loading="eager"
              fetchpriority="high"
            />
          </div>
        </div>
      </div>
    </section>

    <!-- STATS ────────────────────── -->
    <section class="tf-section tf-section--alt" aria-label="Cifras clave">
      <div class="tf-container">
        <dl class="tf-stats-grid">
          <div class="tf-stat">
            <dt class="tf-stat__label">Países</dt>
            <dd class="tf-stat__number">12</dd>
          </div>
          <div class="tf-stat">
            <dt class="tf-stat__label">Clientes</dt>
            <dd class="tf-stat__number">370M</dd>
          </div>
          <div class="tf-stat">
            <dt class="tf-stat__label">Empleados</dt>
            <dd class="tf-stat__number">104K</dd>
          </div>
          <div class="tf-stat">
            <dt class="tf-stat__label">Años conectando</dt>
            <dd class="tf-stat__number">40+</dd>
          </div>
        </dl>
      </div>
    </section>

    <!-- SERVICES / FEATURES ────────── -->
    <section class="tf-section" aria-labelledby="services-title">
      <div class="tf-container">
        <div class="tf-section__header">
          <p class="tf-section__eyebrow">Nuestras soluciones</p>
          <h2 id="services-title" class="tf-section__title">
            Tecnología para cada momento
          </h2>
          <p class="tf-section__subtitle">
            Desde conectividad básica hasta inteligencia artificial: tenemos la solución
            que necesitas para crecer.
          </p>
        </div>
        <div class="tf-feature-grid">

          <article class="tf-card">
            <div class="tf-card__icon" aria-hidden="true">
              <!-- PLACEHOLDER: Use an official icon from Telefonica/mistica-icons.
                   In React: <Icon5GRegular color="currentColor" />
                   In HTML:  Download the SVG from icons/telefonica/regular/ in the mistica-icons repo. -->
            </div>
            <h3 class="tf-card__title">Conectividad empresarial</h3>
            <p class="tf-card__body">
              Fibra, 5G y SD-WAN para mantener tu empresa siempre conectada
              con la máxima fiabilidad.
            </p>
            <a href="/empresas/conectividad" class="tf-text-link" style="margin-top: var(--space-4); display:inline-block;">
              Ver soluciones →
            </a>
          </article>

          <article class="tf-card">
            <div class="tf-card__icon" aria-hidden="true">
              <!-- PLACEHOLDER: Use an official icon from Telefonica/mistica-icons.
                   In React: <IconCloudRegular color="currentColor" />
                   In HTML:  Download the SVG from icons/telefonica/regular/ in the mistica-icons repo. -->
            </div>
            <h3 class="tf-card__title">Cloud e IA</h3>
            <p class="tf-card__body">
              Transforma tu negocio con soluciones cloud escalables e inteligencia
              artificial integrada en tus procesos.
            </p>
            <a href="/empresas/cloud" class="tf-text-link" style="margin-top: var(--space-4); display:inline-block;">
              Ver soluciones →
            </a>
          </article>

          <article class="tf-card">
            <div class="tf-card__icon" aria-hidden="true">
              <!-- PLACEHOLDER: Use an official icon from Telefonica/mistica-icons.
                   In React: <IconSecurityRegular color="currentColor" />
                   In HTML:  Download the SVG from icons/telefonica/regular/ in the mistica-icons repo. -->
            </div>
            <h3 class="tf-card__title">Ciberseguridad</h3>
            <p class="tf-card__body">
              Protege tus activos digitales con nuestras soluciones de seguridad
              gestionada y detección avanzada de amenazas.
            </p>
            <a href="/empresas/seguridad" class="tf-text-link" style="margin-top: var(--space-4); display:inline-block;">
              Ver soluciones →
            </a>
          </article>

        </div>
      </div>
    </section>

    <!-- CTA BANNER ─────────────────── -->
    <section class="tf-section tf-section--alt" aria-label="Llamada a la acción">
      <div class="tf-container">
        <div class="tf-cta-banner" role="complementary">
          <div class="tf-cta-banner__text">
            <h2>¿Listo para conectar tu empresa al futuro?</h2>
            <p>Habla con uno de nuestros expertos y diseña la solución que necesitas.</p>
          </div>
          <div class="tf-cta-banner__actions">
            <a href="/contacto" class="tf-button tf-button--primary-inverse tf-button--lg">
              Solicitar información
            </a>
          </div>
        </div>
      </div>
    </section>

  </main>

  <!-- FOOTER ──────────────────────────────── -->
  <footer class="tf-footer" role="contentinfo">
    <div class="tf-container">

      <div class="tf-footer__grid">

        <!-- Brand column -->
        <div class="tf-footer__brand">
          <a href="/" aria-label="Telefónica — Inicio">
            <!--
              PLACEHOLDER: Replace with approved white Telefónica logo from Brand Factory.
              In React, use: <TelefonicaLogo size={30} type="imagotype" /> from @telefonica/mistica.
              Do NOT recreate, trace, or extract the logo manually.
            -->
            <img src="/img/logo-telefonica-white.svg" alt="Telefónica" width="120" height="30" />
          </a>
          <p>
            Conectamos a personas y empresas para construir un mundo más próspero
            y sostenible.
          </p>
        </div>

        <!-- Links columns -->
        <div>
          <h3 class="tf-footer__col-title">Soluciones</h3>
          <ul class="tf-footer__links" role="list">
            <li><a href="/empresas">Para empresas</a></li>
            <li><a href="/particulares">Para particulares</a></li>
            <li><a href="/empresas/cloud">Cloud e IA</a></li>
            <li><a href="/empresas/seguridad">Ciberseguridad</a></li>
            <li><a href="/empresas/iot">IoT</a></li>
          </ul>
        </div>

        <div>
          <h3 class="tf-footer__col-title">Compañía</h3>
          <ul class="tf-footer__links" role="list">
            <li><a href="/sobre-nosotros">Sobre nosotros</a></li>
            <li><a href="/sostenibilidad">Sostenibilidad</a></li>
            <li><a href="/innovacion">Innovación</a></li>
            <li><a href="/inversores">Inversores</a></li>
            <li><a href="/sala-prensa">Sala de prensa</a></li>
          </ul>
        </div>

        <div>
          <h3 class="tf-footer__col-title">Contacto</h3>
          <ul class="tf-footer__links" role="list">
            <li><a href="/contacto">Formulario de contacto</a></li>
            <li><a href="/empleo">Trabaja con nosotros</a></li>
            <li><a href="/soporte">Soporte</a></li>
          </ul>
        </div>

      </div>

      <!-- Legal bar -->
      <div class="tf-footer__bottom">
        <p class="tf-footer__legal">© [Año] Telefónica S.A. Todos los derechos reservados.</p>
        <ul class="tf-footer__legal-links" role="list">
          <li><a href="/aviso-legal">Aviso legal</a></li>
          <li><a href="/privacidad">Privacidad</a></li>
          <li><a href="/cookies">Cookies</a></li>
          <li><a href="/accesibilidad">Accesibilidad</a></li>
        </ul>
      </div>

    </div>
  </footer>

  <!-- Mobile menu script -->
  <script>
    function toggleMenu(btn) {
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      btn.setAttribute('aria-label', expanded ? 'Abrir menú' : 'Cerrar menú');
      const menu = document.getElementById('mobile-menu');
      menu.classList.toggle('tf-nav__mobile--open', !expanded);
    }
  </script>

</body>
</html>
```

---

## Contact page / form template

```html
<!-- Contact section: place inside <main id="main-content"> -->
<section class="tf-section" aria-labelledby="contact-title">
  <div class="tf-container">
    <div style="max-width: 720px; margin: 0 auto;">

      <div class="tf-section__header">
        <p class="tf-section__eyebrow">Estamos aquí para ayudarte</p>
        <h1 id="contact-title" class="tf-section__title">Contacta con nosotros</h1>
        <p class="tf-section__subtitle">
          Rellena el formulario y un especialista se pondrá en contacto contigo
          en menos de 24 horas.
        </p>
      </div>

      <form method="POST" action="/api/contact" novalidate aria-label="Formulario de contacto">

        <div style="display: grid; gap: 0; grid-template-columns: 1fr;">

          <div style="display: grid; gap: var(--space-5);">

            <!-- Name and surname -->
            <div style="display: grid; gap: var(--space-5); grid-template-columns: 1fr 1fr;">
              <div class="tf-form-group">
                <label for="nombre" class="tf-label tf-label--required">Nombre</label>
                <input
                  type="text"
                  id="nombre"
                  name="nombre"
                  class="tf-input"
                  autocomplete="given-name"
                  required
                  aria-required="true"
                  placeholder="Tu nombre"
                />
                <span class="tf-field-error" id="nombre-error" role="alert" hidden></span>
              </div>
              <div class="tf-form-group">
                <label for="apellidos" class="tf-label tf-label--required">Apellidos</label>
                <input
                  type="text"
                  id="apellidos"
                  name="apellidos"
                  class="tf-input"
                  autocomplete="family-name"
                  required
                  aria-required="true"
                  placeholder="Tus apellidos"
                />
              </div>
            </div>

            <!-- Email -->
            <div class="tf-form-group">
              <label for="email" class="tf-label tf-label--required">Correo electrónico</label>
              <input
                type="email"
                id="email"
                name="email"
                class="tf-input"
                autocomplete="email"
                required
                aria-required="true"
                placeholder="tu@empresa.com"
              />
              <span class="tf-field-hint">Usaremos esta dirección únicamente para responder a tu consulta.</span>
            </div>

            <!-- Company and role -->
            <div style="display: grid; gap: var(--space-5); grid-template-columns: 1fr 1fr;">
              <div class="tf-form-group">
                <label for="empresa" class="tf-label">Empresa</label>
                <input
                  type="text"
                  id="empresa"
                  name="empresa"
                  class="tf-input"
                  autocomplete="organization"
                  placeholder="Nombre de tu empresa"
                />
              </div>
              <div class="tf-form-group">
                <label for="cargo" class="tf-label">Cargo</label>
                <input
                  type="text"
                  id="cargo"
                  name="cargo"
                  class="tf-input"
                  autocomplete="organization-title"
                  placeholder="Tu cargo"
                />
              </div>
            </div>

            <!-- Phone -->
            <div class="tf-form-group">
              <label for="telefono" class="tf-label">Teléfono de contacto</label>
              <input
                type="tel"
                id="telefono"
                name="telefono"
                class="tf-input"
                autocomplete="tel"
                placeholder="+34 600 000 000"
              />
            </div>

            <!-- Service of interest -->
            <div class="tf-form-group">
              <label for="servicio" class="tf-label tf-label--required">Solución de interés</label>
              <select id="servicio" name="servicio" class="tf-select" required aria-required="true">
                <option value="" disabled selected>Selecciona una opción</option>
                <option value="conectividad">Conectividad empresarial</option>
                <option value="cloud">Cloud e IA</option>
                <option value="seguridad">Ciberseguridad</option>
                <option value="iot">IoT</option>
                <option value="otro">Otro</option>
              </select>
            </div>

            <!-- Message -->
            <div class="tf-form-group">
              <label for="mensaje" class="tf-label tf-label--required">Mensaje</label>
              <textarea
                id="mensaje"
                name="mensaje"
                class="tf-textarea"
                rows="5"
                required
                aria-required="true"
                placeholder="Cuéntanos en qué podemos ayudarte..."
              ></textarea>
            </div>

            <!-- Privacy consent -->
            <div class="tf-form-group" style="flex-direction: row; align-items: flex-start; gap: var(--space-3);">
              <input
                type="checkbox"
                id="privacidad"
                name="privacidad"
                required
                aria-required="true"
                style="margin-top: 3px; accent-color: var(--tf-blue); width:16px; height:16px; flex-shrink:0;"
              />
              <label for="privacidad" class="tf-label" style="font-weight: var(--tf-font-regular); cursor:pointer;">
                He leído y acepto la
                <a href="/privacidad" class="tf-text-link">Política de privacidad</a>
                de Telefónica y consiento el tratamiento de mis datos para gestionar mi consulta.
              </label>
            </div>

            <!-- Submit -->
            <div>
              <button type="submit" class="tf-button tf-button--primary tf-button--lg">
                Enviar consulta
              </button>
            </div>

          </div>
        </div>
      </form>

    </div>
  </div>
</section>
```

---

## Landing page — product/service template

```html
<!-- Drop into <main> for a focused product landing -->

<!-- Hero with blue background -->
<section class="tf-hero tf-hero--dark" aria-labelledby="lp-title">
  <div class="tf-container">
    <div style="max-width: 720px; margin: 0 auto; text-align: center;">
      <p class="tf-hero__eyebrow">Conectividad empresarial</p>
      <h1 id="lp-title" class="tf-hero__title">
        Fibra y 5G pensados para tu empresa
      </h1>
      <p class="tf-hero__body" style="margin-left:auto; margin-right:auto;">
        Velocidades simétricas, SLA garantizado y soporte 24/7.
        Porque tu negocio no puede esperar.
      </p>
      <div class="tf-hero__actions" style="justify-content: center;">
        <a href="/contacto"  class="tf-button tf-button--primary tf-button--lg">Solicitar oferta</a>
        <a href="#ventajas"  class="tf-button tf-button--tertiary tf-button--lg" style="color:#fff; border-color:rgba(255,255,255,.4);">Ver ventajas</a>
      </div>
    </div>
  </div>
</section>

<!-- Feature bullets / benefits -->
<section id="ventajas" class="tf-section" aria-labelledby="benefits-title">
  <div class="tf-container">
    <div class="tf-section__header">
      <h2 id="benefits-title" class="tf-section__title">¿Por qué elegir Telefónica?</h2>
    </div>
    <div class="tf-feature-grid">
      <div class="tf-card tf-card--flat">
        <div class="tf-card__icon" aria-hidden="true">
          <!-- PLACEHOLDER: Use official icon from Telefonica/mistica-icons (e.g. 5g-regular.svg) -->
        </div>
        <h3 class="tf-card__title">Velocidad simétrica</h3>
        <p class="tf-card__body">Misma velocidad de subida y bajada. Fundamental para trabajo en la nube y videollamadas.</p>
      </div>
      <div class="tf-card tf-card--flat">
        <div class="tf-card__icon" aria-hidden="true">
          <!-- PLACEHOLDER: Use official icon from Telefonica/mistica-icons (e.g. shield-lock-regular.svg) -->
        </div>
        <h3 class="tf-card__title">SLA garantizado</h3>
        <p class="tf-card__body">Tiempo de resolución comprometido por contrato. Tu continuidad de negocio, asegurada.</p>
      </div>
      <div class="tf-card tf-card--flat">
        <div class="tf-card__icon" aria-hidden="true">
          <!-- PLACEHOLDER: Use official icon from Telefonica/mistica-icons (e.g. support-agent-regular.svg) -->
        </div>
        <h3 class="tf-card__title">Soporte 24/7</h3>
        <p class="tf-card__body">Un equipo técnico especializado disponible en todo momento, sin excepciones.</p>
      </div>
    </div>
  </div>
</section>

<!-- Social proof / testimonial -->
<section class="tf-section tf-section--alt" aria-label="Testimonios">
  <div class="tf-container" style="max-width: 860px; margin: 0 auto; text-align: center;">
    <blockquote style="margin:0;">
      <p style="font-size: clamp(1.125rem, 2vw, 1.375rem); line-height: 1.6; color: var(--tf-text-primary); font-style: italic; margin-bottom: var(--space-6);">
        "Desde que migramos a Telefónica, el tiempo de inactividad de nuestra red cayó
        a prácticamente cero. El equipo de soporte es excepcional."
      </p>
      <footer style="color: var(--tf-text-secondary); font-size: .9375rem;">
        <strong style="color: var(--tf-text-primary);">María González</strong>,
        directora de TI — Empresa Ejemplo S.A.
      </footer>
    </blockquote>
  </div>
</section>

<!-- Final CTA -->
<section class="tf-section" aria-label="Solicitar información">
  <div class="tf-container">
    <div class="tf-cta-banner">
      <div class="tf-cta-banner__text">
        <h2>Empieza hoy mismo</h2>
        <p>Configura tu solución en minutos. Sin permanencia el primer año.</p>
      </div>
      <div class="tf-cta-banner__actions">
        <a href="/contacto" class="tf-button tf-button--primary-inverse tf-button--lg">
          Contactar con ventas
        </a>
      </div>
    </div>
  </div>
</section>
```

---

## Utility classes

```css
/* Text link in content */
.tf-text-link {
  color:           var(--tf-text-link);
  font-weight:     var(--tf-font-medium);
  text-decoration: none;
  transition:      color .15s ease;
}
.tf-text-link:hover {
  color:           var(--tf-blue-70);
  text-decoration: underline;
}

/* Visually hidden (accessible) */
.tf-sr-only {
  position:   absolute;
  width:      1px;
  height:     1px;
  padding:    0;
  margin:     -1px;
  overflow:   hidden;
  clip:       rect(0,0,0,0);
  white-space: nowrap;
  border:     0;
}

/* Skip link */
.tf-skip-link {
  position:        absolute;
  left:            var(--space-4);
  top:             -60px;
  z-index:         999;
  background:      var(--tf-blue);
  color:           #ffffff;
  padding:         .625rem 1.25rem;
  border-radius:   var(--tf-radius-button);
  font-weight:     var(--tf-font-medium);
  font-size:       .9375rem;
  text-decoration: none;
  transition:      top .15s ease;
}
.tf-skip-link:focus { top: var(--space-4); }

/* Tag / badge */
.tf-tag {
  display:         inline-flex;
  align-items:     center;
  padding:         .25rem .75rem;
  border-radius:   24px;
  font-size:       .75rem;
  font-weight:     var(--tf-font-medium);
  line-height:     1.4;
}
.tf-tag--promo {
  background: var(--tf-blue-10);
  color:      var(--tf-blue);
}
.tf-tag--success {
  background: #e8f7ed;
  color:      #1a6335;
}
.tf-tag--warning {
  background: var(--tf-yellow-very-light);
  color:      var(--tf-yellow-dark);
}
.tf-tag--error {
  background: var(--tf-red-very-light);
  color:      var(--tf-red-dark);
}

/* Divider */
.tf-divider {
  border:     none;
  border-top: 1px solid var(--tf-border);
  margin:     var(--space-8) 0;
}
```

---

## Accessibility patterns

### Skip link (required)

Always include the skip link as the first element in `<body>`:
```html
<a href="#main-content" class="tf-skip-link">Saltar al contenido</a>
```

### ARIA landmarks

```html
<header role="banner">
  <nav aria-label="Navegación principal">…</nav>
</header>
<main id="main-content" role="main">…</main>
<aside aria-label="Información relacionada">…</aside>
<footer role="contentinfo">…</footer>
```

### Focus trap for modals

```js
// Trap focus inside a dialog when it opens
function trapFocus(element) {
  const focusable = element.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const first = focusable[0];
  const last  = focusable[focusable.length - 1];
  element.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}
```

---

## Font loading best practice

Since `Telefonica Sans` is a licensed proprietary font, include a notice for the developer:

```html
<!--
  IMPORTANT: Telefonica Sans is a licensed corporate font.
  Do NOT self-host or ship the font files without Telefónica Brand Factory approval.

  If you have access to the licensed files via your Telefónica contract,
  use @font-face with font-display: swap and preload the WOFF2 variant:

  <link rel="preload" href="/fonts/TelefonicaSans-Regular.woff2" as="font" type="font/woff2" crossorigin>

  Without the license, the system-ui stack will render correctly
  as it uses the native system sans-serif.
-->
```

---

## Quick-start checklist for a new corporate site

1. Copy HTML boilerplate → set `lang`, `title`, and `description`.
2. Import `tokens.css` (CSS variables from `brand-guidelines.md`) and `main.css`.
3. Add the skip link and landmark structure.
4. Replace placeholder logo `<img>` with approved Telefónica Brand Factory asset or `TelefonicaLogo` component.
5. Populate navigation links for the site's IA.
6. Adapt the hero copy following the voice guidelines (active verbs, benefit first).
7. Add sections: stats, features, CTA banner.
8. Wire the contact form to the backend (server-side validation is mandatory).
9. Audit: responsive at 375 / 768 / 1024 / 1280px, keyboard navigation, contrast ratios, `alt` text.
10. Add cookie banner and legal links to the footer.

