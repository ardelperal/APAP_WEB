// APAP_WEB — nav burger toggle controller (issue #820, second half of #804).
//
// Vanilla JS IIFE. Loaded with ``defer`` from ``base.html`` and
// ``base_mobile.html``. The button (``#nav-burger-toggle``) and the
// nav (``#nav-main``) come from the structural slice #819.
//
// Single source of truth for the open state: the button's
// ``aria-expanded`` attribute. The nav's ``hidden`` property mirrors
// that state so CSS ``[hidden]`` keeps the mobile menu out of the
// layout until open. All handlers (toggle, Escape, click-outside,
// route-change) read or write ``setOpen`` and route through this
// single function so the visual state and the announced state stay
// in lock-step.
//
// Vanilla, no framework. No new dependencies. CSP-compliant
// (``script-src 'self'`` allows same-origin scripts per
// ``app/core/middleware.py::SecurityHeadersMiddleware``).
(function () {
  "use strict";

  var btn = document.getElementById("nav-burger-toggle");
  var nav = document.getElementById("nav-main");
  if (!btn || !nav) return;

  // Mirror the initial aria-expanded so SSR and JS agree.
  var open = btn.getAttribute("aria-expanded") === "true";

  // Selector for focusable descendants. ``tabindex="-1"`` is excluded so
  // the brand link (which carries ``tabindex="-1"`` after slice #818)
  // does not enter the trap; ``disabled`` is excluded for symmetry.
  function focusables() {
    return Array.prototype.slice
      .call(
        nav.querySelectorAll(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      )
      .filter(function (el) {
        return !el.disabled;
      });
  }

  function setOpen(next) {
    open = Boolean(next);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    nav.hidden = !open;
    // Issue #901: the rail redesign (#868) gave ``#nav-main`` the Tailwind
    // ``hidden`` class (``display: none`` regardless of the ``hidden``
    // attribute), which kept the panel invisible on mobile even with the
    // attribute cleared. Toggle the class in lock-step with the attribute
    // so the computed visibility matches the announced state on both
    // bases (desktop rail keeps ``md:flex``; the mobile base falls back
    // to its default block flow, as before #868).
    nav.classList.toggle("hidden", !open);
    if (open) {
      var first = focusables()[0];
      if (first) first.focus();
    } else {
      // Return focus to the toggle so keyboard users do not lose
      // their place after closing the menu.
      btn.focus();
    }
  }

  // --- Toggle: click on the button ---
  btn.addEventListener("click", function () {
    setOpen(!open);
  });

  // --- Escape: close without losing focus context ---
  document.addEventListener("keydown", function (e) {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      return;
    }
    // --- Tab focus trap: keep focus inside the open nav ---
    if (e.key === "Tab") {
      var items = focusables();
      if (items.length === 0) return;
      var first = items[0];
      var last = items[items.length - 1];
      var active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  // --- Click outside: close when target is neither the button nor the nav ---
  document.addEventListener("click", function (e) {
    if (!open) return;
    var target = e.target;
    if (target && target.closest && target.closest("#nav-burger-toggle, #nav-main")) {
      return;
    }
    setOpen(false);
  });

  // --- Route-change close: closing before navigation prevents a stale
  //     nav from appearing after the new page renders. The project does
  //     not use HTMX (verified: ``grep -r "htmx" app/templates`` is
  //     empty), so full-page navigation applies. The listener fires
  //     before the default link navigation; the menu closes, then the
  //     browser navigates. ---
  nav.addEventListener("click", function (e) {
    if (!open) return;
    var link = e.target.closest && e.target.closest("a[href]");
    if (link) setOpen(false);
  });

  // --- Browser back/forward also clears the menu state ---
  window.addEventListener("popstate", function () {
    if (open) setOpen(false);
  });
})();
