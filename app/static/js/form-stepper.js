/*
 * APAP_WEB — reusable form stepper controller (issue #821).
 *
 * Vanilla JS, no framework. Turns any <form> that follows the stepper
 * markup contract into a multi-step wizard:
 *
 *   <form data-stepper="true" data-step-current="1"
 *         data-step-validate='[{"step":1,"selector":"#step-1 input","required":true},...]'>
 *     <ol class="stepper" data-stepper-list>
 *       <li data-step="1">…</li>
 *     </ol>
 *     <fieldset id="step-1" data-step-panel="1" hidden>…</fieldset>
 *     <div data-step-nav>
 *       <button type="button" data-step-prev>Anterior</button>
 *       <button type="button" data-step-next>Siguiente</button>
 *       <button type="submit" data-step-submit hidden>Enviar</button>
 *     </div>
 *   </form>
 *
 * Behavior:
 * - "Siguiente" stays disabled until visible required fields on the
 *   current step are valid; a failed advance still focuses the first error.
 * - "Anterior" goes back without validating; fields keep their values.
 * - Completed (or previously reached) steps are clickable in the list.
 * - The submit button is visible+enabled only on the last step.
 * - A11y: aria-current="step" on the visible list entry, role="region"
 *   + aria-labelledby per panel, panels toggled via [hidden].
 *
 * Self-initializes on DOMContentLoaded from every form[data-stepper].
 * Same-origin static asset: satisfies the CSP script-src 'self' baseline.
 */
(function () {
    'use strict';

    /** True when the element is a required-but-empty field. */
    function isEmptyField(el) {
        if (el.type === 'checkbox' || el.type === 'radio') {
            return !el.checked;
        }
        return String(el.value).trim() === '';
    }

    /** Ignore hidden or disabled controls, including collapsed inner groups. */
    function isVisibleField(el) {
        if (el.type === 'hidden' || el.disabled) {
            return false;
        }
        for (var node = el; node && !node.hasAttribute('data-step-panel'); node = node.parentElement) {
            var style = getComputedStyle(node);
            if (node.hidden || style.display === 'none' || style.visibility === 'hidden') {
                return false;
            }
        }
        return true;
    }

    /**
     * Validate step `stepNumber` against the data-step-validate entries.
     * Returns the list of invalid elements ([] when the step passes).
     */
    function findInvalidFields(form, rules, stepNumber) {
        var invalid = [];
        var panel = form.querySelector('[data-step-panel="' + stepNumber + '"]');
        rules.forEach(function (rule) {
            if (Number(rule.step) !== stepNumber || !rule.required || !rule.selector) {
                return;
            }
            form.querySelectorAll(rule.selector).forEach(function (el) {
                if (isVisibleField(el) && (isEmptyField(el) || !el.checkValidity())) {
                    invalid.push(el);
                }
            });
        });
        if (panel) {
            panel.querySelectorAll('input, select, textarea').forEach(function (el) {
                if (isVisibleField(el) && !el.checkValidity() && invalid.indexOf(el) === -1) {
                    invalid.push(el);
                }
            });
        }
        return invalid;
    }

    function initForm(form) {
        var listItems = Array.prototype.slice.call(
            form.querySelectorAll('[data-stepper-list] [data-step]')
        );
        var panels = Array.prototype.slice.call(
            form.querySelectorAll('[data-step-panel]')
        );
        var nav = form.querySelector('[data-step-nav]');
        var prevBtn = nav ? nav.querySelector('[data-step-prev]') : null;
        var nextBtn = nav ? nav.querySelector('[data-step-next]') : null;
        var submitBtn = nav ? nav.querySelector('[data-step-submit]') : null;

        if (!listItems.length || !panels.length || !nav) {
            return; // incomplete contract: leave the form untouched
        }

        var rules = [];
        try {
            rules = JSON.parse(form.getAttribute('data-step-validate') || '[]');
        } catch (err) {
            rules = []; // malformed JSON: every step passes, wizard still works
        }

        var panelNumbers = panels.map(function (panel) {
            return Number(panel.getAttribute('data-step-panel'));
        });
        var lastStep = Math.max.apply(null, panelNumbers);

        var current = parseInt(form.getAttribute('data-step-current') || '1', 10) || 1;
        var passedSteps = {}; // steps whose validation succeeded
        var maxReached = current;
        form.noValidate = true; // let the controller reveal hidden-step errors before native validation

        function panelFor(stepNumber) {
            return panels.filter(function (panel) {
                return Number(panel.getAttribute('data-step-panel')) === stepNumber;
            })[0];
        }

        function goTo(stepNumber) {
            current = stepNumber;
            if (current > maxReached) {
                maxReached = current;
            }
            render();
        }

        function render() {
            listItems.forEach(function (item) {
                var step = Number(item.getAttribute('data-step'));
                item.classList.toggle('is-current', step === current);
                item.classList.toggle('is-complete', Boolean(passedSteps[step]));
                if (step === current) {
                    item.setAttribute('aria-current', 'step');
                    item.removeAttribute('data-step-clickable');
                    item.removeAttribute('role');
                    item.removeAttribute('tabindex');
                } else if (step <= maxReached) {
                    item.removeAttribute('aria-current');
                    item.setAttribute('data-step-clickable', 'true');
                    item.setAttribute('role', 'button');
                    item.setAttribute('tabindex', '0');
                } else {
                    item.removeAttribute('aria-current');
                    item.removeAttribute('data-step-clickable');
                    item.removeAttribute('role');
                    item.removeAttribute('tabindex');
                }
            });

            panels.forEach(function (panel) {
                var step = Number(panel.getAttribute('data-step-panel'));
                panel.hidden = step !== current;
                if (panel.getAttribute('role') !== 'region') {
                    panel.setAttribute('role', 'region');
                }
                if (!panel.getAttribute('aria-labelledby')) {
                    var label = form.querySelector(
                        '[data-stepper-list] [data-step="' + step + '"] .stepper-label[id]'
                    );
                    if (label) {
                        panel.setAttribute('aria-labelledby', label.id);
                    }
                }
            });

            if (prevBtn) {
                prevBtn.disabled = current === 1;
            }
            if (nextBtn) {
                nextBtn.hidden = current === lastStep;
                nextBtn.disabled = current === lastStep || findInvalidFields(form, rules, current).length > 0;
            }
            if (submitBtn) {
                submitBtn.hidden = current !== lastStep;
                submitBtn.disabled = current !== lastStep;
            }
        }

        function validateAndAdvance() {
            var invalid = findInvalidFields(form, rules, current);
            if (invalid.length) {
                invalid.forEach(function (el) {
                    el.setAttribute('aria-invalid', 'true');
                });
                invalid[0].focus();
                return;
            }
            passedSteps[current] = true;
            form.querySelectorAll('[aria-invalid="true"]').forEach(function (el) {
                el.removeAttribute('aria-invalid');
            });
            if (current < lastStep) {
                goTo(current + 1);
            }
        }

        function validateWholeForm(event) {
            for (var step = 1; step <= lastStep; step += 1) {
                var invalid = findInvalidFields(form, rules, step);
                if (invalid.length) {
                    event.preventDefault();
                    passedSteps[step] = false;
                    goTo(step);
                    invalid.forEach(function (el) {
                        el.setAttribute('aria-invalid', 'true');
                    });
                    invalid[0].focus();
                    return;
                }
            }
        }

        function updateCurrentValidation(event) {
            if (event.target && event.target.matches('[aria-invalid="true"]') &&
                    event.target.checkValidity() && !isEmptyField(event.target)) {
                event.target.removeAttribute('aria-invalid');
            }
            if (findInvalidFields(form, rules, current).length) {
                passedSteps[current] = false;
            }
            render();
        }

        form.addEventListener('input', updateCurrentValidation);
        form.addEventListener('change', updateCurrentValidation);
        form.addEventListener('submit', validateWholeForm);

        if (nextBtn) {
            nextBtn.addEventListener('click', validateAndAdvance);
        }
        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                if (current > 1) {
                    goTo(current - 1); // going back never validates
                }
            });
        }

        listItems.forEach(function (item) {
            function jump() {
                var step = Number(item.getAttribute('data-step'));
                if (step !== current && step <= maxReached) {
                    goTo(step); // completed/previous steps: fields preserved
                }
            }
            item.addEventListener('click', jump);
            item.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    jump();
                }
            });
        });

        render();
    }

    function initAll() {
        document.querySelectorAll('form[data-stepper="true"]').forEach(initForm);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll(); // script injected after DOMContentLoaded (defer/cached)
    }
})();
