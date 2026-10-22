// Theme: inherit Home Assistant's current theme when running inside Ingress.
//
// The Ingress iframe is served from the same origin as Home Assistant, so the
// parent document can be read. Everything is wrapped in try/catch: standalone,
// cross-origin or sandboxed use keeps the built-in HA-like light/dark defaults
// of app.css (chosen by prefers-color-scheme). Runs in <head> to avoid a flash.
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  var VARS = [
    "--primary-color", "--dark-primary-color", "--light-primary-color", "--accent-color",
    "--text-primary-color", "--primary-text-color", "--secondary-text-color",
    "--disabled-text-color", "--divider-color", "--shadow-color",
    "--card-background-color", "--primary-background-color", "--secondary-background-color",
    "--error-color", "--success-color", "--warning-color",
    "--app-header-background-color", "--app-header-text-color",
    "--input-fill-color", "--input-idle-line-color",
    "--ha-card-border-radius", "--ha-card-border-width",
    "--color-1", "--color-2", "--color-3", "--color-4", "--color-5"
  ];
  var FONT_VAR = "--ha-font-family-body";

  function parentRoot() {
    try {
      if (window.parent && window.parent !== window) {
        return window.parent.document.documentElement; // throws if cross-origin
      }
    } catch (e) { /* not readable */ }
    return null;
  }

  // Resolve any CSS colour string to [r, g, b] using the browser's own parser.
  function toRgb(value) {
    var probe = document.createElement("span");
    probe.style.color = value;
    if (!probe.style.color) { return null; }
    root.appendChild(probe);
    var match = /rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)/.exec(getComputedStyle(probe).color);
    root.removeChild(probe);
    return match ? [+match[1], +match[2], +match[3]] : null;
  }

  function isDark(rgb) {
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255 < 0.5;
  }

  function sync() {
    try {
      var parent = parentRoot();
      if (!parent) { return; }
      var computed = window.parent.getComputedStyle(parent);
      var seen = 0;
      VARS.forEach(function (name) {
        var value = computed.getPropertyValue(name).trim();
        if (value) { root.style.setProperty(name, value); seen += 1; }
        else { root.style.removeProperty(name); }
      });
      if (!seen) { return; } // not a Home Assistant page: keep the defaults

      var font = computed.getPropertyValue(FONT_VAR).trim() ||
        window.parent.getComputedStyle(window.parent.document.body).fontFamily;
      if (font) { root.style.setProperty(FONT_VAR, font); }

      // Follow HA's own light/dark mode, which can differ from the OS setting.
      var background = computed.getPropertyValue("--primary-background-color").trim();
      var rgb = background && toRgb(background);
      if (rgb) { root.setAttribute("data-theme", isDark(rgb) ? "dark" : "light"); }
    } catch (e) { /* keep the built-in defaults */ }
  }

  sync();
  try {
    var parent = parentRoot();
    if (parent) {
      var pending = false;
      var again = function () {
        if (pending) { return; }
        pending = true;
        window.requestAnimationFrame(function () { pending = false; sync(); });
      };
      new MutationObserver(again).observe(parent, { attributes: true });
      window.addEventListener("focus", again);
      document.addEventListener("visibilitychange", again);
    }
  } catch (e) { /* no live updates */ }

  // Auto-submitting controls ([data-autosubmit], e.g. the app-bar vehicle select).
  // Kept here, not in the deferred app.js: that file can still be loading when the
  // user picks a vehicle on a fresh session, and the choice would be lost. A
  // delegated listener on document works before any element exists. Without
  // JavaScript the form's own button (<noscript>) submits.
  document.addEventListener("change", function (event) {
    var control = event.target;
    if (!control.matches || !control.matches("[data-autosubmit]") || !control.form) { return; }
    // A choice that needs more input first (e.g. "New vehicle..." needs a name) does not submit.
    if (control.getAttribute("data-autosubmit-skip") === control.value) { return; }
    if (control.form.requestSubmit) { control.form.requestSubmit(); } else { control.form.submit(); }
  });
})();
