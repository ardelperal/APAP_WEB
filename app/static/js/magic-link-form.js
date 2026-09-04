// The /auth/magic/start endpoint expects a JSON body (Content-Type:
// application/json) per the M1 magic-link API contract. The default
// <form> submit sends application/x-www-form-urlencoded, which the
// route rejects with 400. This handler intercepts the submit, posts
// JSON via fetch, and surfaces a status message in #magic-link-status.
// The CSRF token is read from the hidden input (set by the
// csrf_token_context_processor on the template render).
//
// Note: this file is referenced from app/templates/login.html via
// <script src="/static/js/magic-link-form.js">. The template HTML
// itself does NOT contain any inline <script> tags, so the deployed
// app's CSP (script-src 'self') permits this external script.
(function () {
  const form = document.getElementById("magic-link-form");
  const status = document.getElementById("magic-link-status");
  if (!form || !status) return;
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const button = form.querySelector("button[type=submit]");
    if (button) button.disabled = true;
    status.classList.remove("hidden", "text-success", "text-error");
    status.classList.add("text-text-muted");
    status.textContent = "Enviando enlace…";
    const data = new FormData(form);
    const body = {};
    for (const [k, v] of data.entries()) body[k] = v;
    try {
      const r = await fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "same-origin",
      });
      if (r.status === 200) {
        status.classList.remove("text-text-muted", "text-error");
        status.classList.add("text-success");
        status.textContent =
          "Te enviamos un enlace. Revisa tu buzón de entrada y sigue las instrucciones.";
        form.reset();
      } else if (r.status === 400) {
        status.classList.remove("text-text-muted", "text-success");
        status.classList.add("text-error");
        status.textContent = "El correo no es válido. Inténtalo de nuevo.";
      } else {
        const text = await r.text().catch(() => "");
        status.classList.remove("text-text-muted", "text-success");
        status.classList.add("text-error");
        status.textContent =
          "Error inesperado (" + r.status + "). " + (text || "").slice(0, 200);
      }
    } catch (err) {
      status.classList.remove("text-text-muted", "text-success");
      status.classList.add("text-error");
      status.textContent = "Error de red: " + (err && err.message ? err.message : "desconocido");
    } finally {
      if (button) button.disabled = false;
    }
  });
})();
