// Glovebox page script: dialogs, small live helpers and inline SVG charts.
// Every feature degrades to plain links and forms when this script does not run.
(function () {
  "use strict";
  var DIALOG_HEADER = { "X-Glovebox-Dialog": "1" };
  var overlay = document.getElementById("overlay");

  /* ---------- dialogs ---------- */
  function closeOverlay() { if (overlay) { overlay.innerHTML = ""; } }

  function show(html) {
    overlay.innerHTML = html;
    var first = overlay.querySelector("input:not([type=hidden]), select, textarea");
    if (first && !overlay.querySelector(".chooser, .confirm")) { first.focus(); }
    bindCalc(overlay);
    bindStationSelect(overlay);
    bindOdometerHint(overlay);
    bindFuelType(overlay);
    bindCopy(overlay);
    bindQuick(overlay);
  }

  function openDialog(href) {
    fetch(href, { headers: DIALOG_HEADER, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(show)
      .catch(function () { window.location.href = href; });
  }

  function submitDialog(form, submitter) {
    var data = new URLSearchParams(new FormData(form));
    if (submitter && submitter.name) { data.append(submitter.name, submitter.value); }
    var action = (submitter && submitter.getAttribute("formaction")) || form.getAttribute("action") || window.location.href;
    fetch(action, {
      method: (form.getAttribute("method") || "get").toUpperCase(),
      body: data, redirect: "manual", credentials: "same-origin",
      headers: Object.assign({ "Content-Type": "application/x-www-form-urlencoded" }, DIALOG_HEADER)
    }).then(function (r) {
      if (r.type === "opaqueredirect" || (r.status >= 300 && r.status < 400)) {
        window.location.reload();
        return null;
      }
      return r.text().then(show);
    }).catch(function () { form.submit(); });
  }

  document.addEventListener("click", function (event) {
    var confirmer = event.target.closest("[data-confirm]");
    if (confirmer && !window.confirm(confirmer.getAttribute("data-confirm"))) {
      event.preventDefault();
      return;
    }
    var closer = event.target.closest("[data-close]");
    if (closer && overlay && overlay.contains(closer)) {
      event.preventDefault();
      closeOverlay();
      return;
    }
    var scrim = event.target.closest("[data-scrim]");
    if (scrim && event.target === scrim) { closeOverlay(); return; }
    var opener = event.target.closest("a[data-dialog]");
    if (opener && !event.ctrlKey && !event.metaKey && !event.shiftKey && overlay) {
      event.preventDefault();
      openDialog(opener.href);
    }
    document.querySelectorAll("details.customise[open]").forEach(function (pop) {
      if (!pop.contains(event.target) || event.target.closest("[data-close-customise]")) { pop.removeAttribute("open"); }
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") { return; }
    closeOverlay();
    document.querySelectorAll("details.customise[open]").forEach(function (pop) { pop.removeAttribute("open"); });
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    // A download button submits natively: a fetch would swallow the file.
    if (event.submitter && event.submitter.hasAttribute("data-download")) { return; }
    if (overlay && overlay.contains(form)) {
      event.preventDefault();
      submitDialog(form, event.submitter);
    }
  });

  /* ---------- summary-card choice ---------- */
  /* Auto-submitting controls are handled by theme.js, which runs before the page is parsed. */
  document.addEventListener("change", function (event) {
    var control = event.target;
    if (control.closest("[data-cards-form]")) { saveCards(control.form); }
  });

  /* ---------- toast ---------- */
  function toast(message) {
    var old = document.querySelector(".toast");
    if (old) { old.remove(); }
    var node = document.createElement("div");
    node.className = "toast";
    node.setAttribute("role", "status");
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(function () { node.remove(); }, 3000);
  }

  /* ---------- summary cards ---------- */
  function saveCards(form) {
    function ticked(name) {
      return Array.prototype.map.call(
        form.querySelectorAll("input[name=" + name + "]:checked"), function (i) { return i.value; });
    }
    var cards = ticked("card"), groups = ticked("summary");
    document.querySelectorAll("[data-card]").forEach(function (card) {
      card.hidden = cards.indexOf(card.getAttribute("data-card")) < 0;
    });
    form.querySelectorAll("input[name=offered]").forEach(function (offer) {
      document.querySelectorAll('[data-summary="' + offer.value + '"]').forEach(function (group) {
        group.hidden = groups.indexOf(offer.value) < 0;
      });
    });
    fetch(form.action, {
      method: "POST", body: new URLSearchParams(new FormData(form)),
      redirect: "manual", credentials: "same-origin"
    }).catch(function () { toast("Could not save the choice"); });
  }

  /* ---------- refuelling form: two of three ---------- */
  function number(text) {
    var value = parseFloat(String(text).replace(/\s/g, "").replace(",", "."));
    return isFinite(value) ? value : null;
  }

  function bindCalc(root) {
    var group = root.querySelector("[data-price-fields]");
    if (!group || group.dataset.bound) { return; }
    group.dataset.bound = "1";
    var box = {};
    group.querySelectorAll("[data-calc]").forEach(function (f) {
      box[f.getAttribute("data-calc")] = f.querySelector("input");
    });
    var recent = [];
    function touch(name) {
      recent = recent.filter(function (n) { return n !== name; });
      recent.push(name);
      if (recent.length < 2) { return; }
      var inputs = recent.slice(-2);
      var target = ["litres", "price_per_litre", "total"].filter(function (n) { return inputs.indexOf(n) < 0; })[0];
      var a = number(box[inputs[0]].value), b = number(box[inputs[1]].value);
      if (a === null || b === null) { return; }
      var v = {}; v[inputs[0]] = a; v[inputs[1]] = b;
      var out = null;
      if (target === "total") { out = v.litres * v.price_per_litre; }
      else if (target === "litres" && v.price_per_litre) { out = v.total / v.price_per_litre; }
      else if (target === "price_per_litre" && v.litres) { out = v.total / v.litres; }
      if (out !== null && isFinite(out)) {
        box[target].value = out.toFixed(target === "price_per_litre" ? 3 : 2);
        box[target].closest(".field").classList.add("computed");
      }
    }
    Object.keys(box).forEach(function (name) {
      box[name].addEventListener("input", function () {
        box[name].closest(".field").classList.remove("computed");
        touch(name);
      });
    });
  }

  function bindStationSelect(root) {
    var select = root.querySelector("[data-station-select]");
    var fields = root.querySelector("[data-new-station]");
    if (!select || !fields || select.dataset.bound) { return; }
    select.dataset.bound = "1";
    function sync() {
      if (select.value === "__new") { fields.removeAttribute("data-closed"); }
      else { fields.setAttribute("data-closed", ""); }
    }
    select.addEventListener("change", sync);
    sync();
  }

  /* A select with data-reveal-select="<id>" shows that element only while its
     value equals the element's data-reveal; without JavaScript it stays visible. */
  function bindRevealSelect(root) {
    root.querySelectorAll("[data-reveal-select]").forEach(function (select) {
      var target = document.getElementById(select.getAttribute("data-reveal-select"));
      if (!target || select.dataset.bound) { return; }
      select.dataset.bound = "1";
      function sync() {
        if (select.value === target.getAttribute("data-reveal")) { target.removeAttribute("data-closed"); }
        else { target.setAttribute("data-closed", ""); }
      }
      select.addEventListener("change", sync);
      sync();
    });
  }

  /* A button with data-copy="<input id>" copies that input's text. It is hidden
     in the markup and shown here, because without JavaScript it would do nothing.
     The clipboard API needs a secure page; plain HTTP falls back to execCommand. */
  function bindCopy(root) {
    root.querySelectorAll("[data-copy]").forEach(function (button) {
      var input = document.getElementById(button.getAttribute("data-copy"));
      if (!input || button.dataset.bound) { return; }
      button.dataset.bound = "1";
      button.hidden = false;
      button.addEventListener("click", function () {
        function done() { toast("Copied"); }
        function fallback() {
          input.select();
          if (document.execCommand("copy")) { done(); } else { toast("Could not copy"); }
        }
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(input.value).then(done, fallback);
        } else { fallback(); }
      });
    });
  }

  /* ---------- charts ---------- */
  var SVG = "http://www.w3.org/2000/svg";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var SERIES = ["var(--color-1)", "var(--color-3)", "var(--color-2)", "var(--color-4)", "var(--color-5)"];
  var KEY_COLOUR = {
    fuel: "var(--color-1)", service: "var(--color-2)", insurance: "var(--color-3)",
    registration: "var(--color-4)", other: "var(--color-5)"
  };

  function el(name, attrs, text) {
    var node = document.createElementNS(SVG, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) { node.textContent = text; }
    return node;
  }
  function tip(node, text) { node.appendChild(el("title", {}, text)); return node; }
  function isPhone() { return window.matchMedia("(max-width: 699px)").matches; }
  function fmt(n) { return String(Math.round(n * 100) / 100).replace(".", ","); }
  function dayMs(iso) { return new Date(iso + "T12:00:00Z").getTime(); }

  function frame(w, h, label) {
    return el("svg", { viewBox: "0 0 " + w + " " + h, role: "img", "aria-label": label });
  }

  function niceStep(span, ticks) {
    var raw = span / ticks, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }

  function consumptionChart(host, series) {
    var W = isPhone() ? 340 : 760, H = isPhone() ? 200 : 240, L = 38, R = 8, T = 10, B = 26;
    var all = [];
    series.forEach(function (s) { s.points.concat(s.monthly || []).forEach(function (p) { all.push(p); }); });
    var times = all.map(function (p) { return dayMs(p.date); });
    var t0 = Math.min.apply(null, times), t1 = Math.max.apply(null, times);
    var values = all.map(function (p) { return p.value; });
    var lo = Math.floor(Math.min.apply(null, values) - 0.5), hi = Math.ceil(Math.max.apply(null, values) + 0.5);
    var step = Math.max(1, niceStep(hi - lo, 5));
    var svg = frame(W, H, "Consumption over time");
    function x(ms) { return L + (ms - t0) / Math.max(1, t1 - t0) * (W - L - R); }
    function y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
    for (var v = lo; v <= hi; v += step) {
      svg.appendChild(el("line", { "class": "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      svg.appendChild(el("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    }
    var ticks = isPhone() ? 3 : 6;
    for (var i = 0; i <= ticks; i++) {
      var ms = t0 + (t1 - t0) * i / ticks, d = new Date(ms);
      svg.appendChild(el("text", { x: x(ms), y: H - 6, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" },
        MONTHS[d.getUTCMonth()] + " " + String(d.getUTCFullYear()).slice(2)));
    }
    var legend = document.createElement("div");
    legend.className = "legend";
    series.forEach(function (s, index) {
      var colour = SERIES[index % SERIES.length];
      function line(list, width, opacity) {
        return el("polyline", {
          fill: "none", stroke: colour, "stroke-width": width, "stroke-linejoin": "round",
          "stroke-linecap": "round", opacity: opacity,
          points: list.map(function (p) { return x(dayMs(p.date)).toFixed(1) + "," + y(p.value).toFixed(1); }).join(" ")
        });
      }
      svg.appendChild(line(s.points, 1, 0.35));
      s.points.forEach(function (p) {
        svg.appendChild(tip(el("circle", {
          cx: x(dayMs(p.date)).toFixed(1), cy: y(p.value).toFixed(1), r: 2.5,
          fill: colour, "fill-opacity": 0.3, stroke: colour, "stroke-opacity": 0.5, "stroke-width": 1
        }), s.name + " · " + p.date + " · " + fmt(p.value) + " L/100 km"));
      });
      var monthly = s.monthly || [];
      svg.appendChild(line(monthly, 3, 1));
      monthly.forEach(function (p) {
        svg.appendChild(tip(el("circle", {
          cx: x(dayMs(p.date)).toFixed(1), cy: y(p.value).toFixed(1), r: 3.5,
          fill: colour, stroke: "var(--card-background-color)", "stroke-width": 1.5
        }), s.name + " · " + p.date.slice(0, 7) + " average · " + fmt(p.value) + " L/100 km"));
      });
      legend.insertAdjacentHTML("beforeend", '<span><i style="background:' + colour + '"></i></span>');
      legend.lastChild.appendChild(document.createTextNode(s.name));
    });
    legend.insertAdjacentHTML("beforeend", "<span>L/100 km · line: monthly average · dots: single full tanks</span>");
    host.appendChild(svg);
    host.appendChild(legend);
  }

  function costChart(host, data) {
    var W = isPhone() ? 340 : 760, H = isPhone() ? 220 : 260, L = 44, R = 6, T = 10, B = 26;
    var months = data.months, n = months.length;
    var totals = months.map(function (m, i) {
      return data.costs.reduce(function (sum, c) { return sum + c.values[i]; }, 0);
    });
    var step = niceStep(Math.max.apply(null, totals.concat([1])), 4);
    var max = Math.ceil(Math.max.apply(null, totals.concat([1])) / step) * step;
    var svg = frame(W, H, "Monthly cost by type");
    function y(v) { return T + (1 - v / max) * (H - T - B); }
    for (var v = 0; v <= max + 1e-9; v += step) {
      svg.appendChild(el("line", { "class": "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      svg.appendChild(el("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    }
    var slot = (W - L - R) / n, bw = Math.min(34, slot * 0.62);
    var every = Math.ceil(n / (isPhone() ? 6 : 14));
    months.forEach(function (m, i) {
      var cx = L + slot * (i + 0.5), acc = 0;
      data.costs.forEach(function (c) {
        var value = c.values[i];
        if (value <= 0) { return; }
        var top = y(acc + value), height = y(acc) - top;
        acc += value;
        svg.appendChild(tip(el("rect", {
          x: (cx - bw / 2).toFixed(1), y: top.toFixed(1), width: bw.toFixed(1),
          height: Math.max(0, height - 1).toFixed(1), rx: 2, fill: KEY_COLOUR[c.key] || SERIES[4]
        }), MONTHS[+m.slice(5) - 1] + " " + m.slice(0, 4) + " · " + c.label + " · " +
          fmt(value) + " " + data.currency));
      });
      if (i % every === 0) {
        svg.appendChild(el("text", { x: cx, y: H - 6, "text-anchor": "middle" }, MONTHS[+m.slice(5) - 1]));
      }
    });
    host.appendChild(svg);
  }

  function drawCharts() {
    var holder = document.getElementById("chart-data");
    if (!holder) { return; }
    var data = JSON.parse(holder.textContent);
    document.querySelectorAll("[data-chart]").forEach(function (host) {
      host.textContent = "";
      if (host.getAttribute("data-chart") === "consumption" && data.consumption.length) {
        consumptionChart(host, data.consumption);
      } else if (host.getAttribute("data-chart") === "costs" && data.months.length) {
        costChart(host, data);
      }
    });
  }

  /* ---------- refuel form: fuel type follows the vehicle choice ---------- */
  function bindFuelType(root) {
    var tag = root.querySelector("[data-fuel-types]");
    var vehicle = root.querySelector("#i-vehicle_id");
    if (!tag || !vehicle || tag.dataset.bound) { return; }
    tag.dataset.bound = "1";
    var types = {};
    try { types = JSON.parse(tag.dataset.fuelTypes || "{}"); } catch (e) { return; }
    vehicle.addEventListener("change", function () {
      tag.textContent = types[vehicle.value] ? "\u00b7 " + types[vehicle.value] : "";
    });
  }

  /* ---------- expense form: last recorded odometer follows vehicle and date ---------- */
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function bindOdometerHint(root) {
    var hint = root.querySelector("[data-odo-hint]");
    var vehicle = root.querySelector("#i-vehicle_id");
    var day = root.querySelector("#i-date");
    if (!hint || !vehicle || !day || hint.dataset.bound) { return; }
    hint.dataset.bound = "1";
    var steps = {};
    try { steps = JSON.parse(hint.dataset.steps || "{}"); } catch (e) { return; }
    var text = hint.querySelector("[data-odo-text]");
    var input = "placeholder" in hint.dataset ? root.querySelector("#i-odometer_km") : null;
    function update() {
      if (input) { input.placeholder = "0"; }
      if (!vehicle.value) { text.textContent = "Choose a vehicle to see its last recorded odometer."; return; }
      var last = null;
      (steps[vehicle.value] || []).forEach(function (s) {
        if (s[0] === "" || (day.value && s[0] <= day.value)) { last = s; }
      });
      if (!last) { text.textContent = "No earlier reading for this vehicle. Entering the odometer is recommended."; return; }
      var km = last[1].toLocaleString("en-US", { maximumFractionDigits: 1 }) + "\u00a0km";
      if (input) { input.placeholder = last[1].toLocaleString("en-US", { maximumFractionDigits: 1 }); }
      var when = last[0] === "" ? "initial"
        : parseInt(last[0].slice(8), 10) + "\u00a0" + MONTHS[parseInt(last[0].slice(5, 7), 10) - 1];
      text.textContent = "Last recorded: " + km + " (" + when + "). Left empty, this is used and marked as estimated.";
    }
    vehicle.addEventListener("change", update);
    day.addEventListener("change", update);
    day.addEventListener("input", update);
  }

  function chipDate(day, chip) {
    var iso = day.value;
    if (!iso) { return; }
    var t = new Date(), now = t.getFullYear() + "-" + ("0" + (t.getMonth() + 1)).slice(-2) + "-" + ("0" + t.getDate()).slice(-2);
    var short = parseInt(iso.slice(8), 10) + "\u00a0" + MONTHS[parseInt(iso.slice(5, 7), 10) - 1];
    chip.textContent = iso === now ? "Today, " + short : short;
  }

  /* Quick service / expense: title chips, odometer hint, Save enabled when complete. */
  function bindQuickEntry(form) {
    var title = form.querySelector("#i-title"), amount = form.querySelector("#i-amount");
    var odo = form.querySelector("#i-odometer_km"), save = form.querySelector("[data-quick-save]");
    var hint = form.querySelector("[data-odo-quick]"), day = form.querySelector("#i-date");
    var groups = form.querySelectorAll("[data-title-chips]");
    var types = form.querySelectorAll("input[name=category]");
    var initial = hint.textContent.trim();
    var last = hint.dataset.lastKm === "" ? null : parseFloat(hint.dataset.lastKm);
    function category() {
      var picked = form.querySelector("input[name=category]:checked");
      return picked ? picked.value : "maintenance";
    }
    function showChips() {
      groups.forEach(function (group) {
        group.hidden = group.getAttribute("data-title-chips") !== category();
        group.querySelectorAll(".chip").forEach(function (chip) {
          chip.classList.toggle("active", chip.getAttribute("data-title") === title.value);
        });
      });
    }
    function update() {
      var km = number(odo.value);
      hint.classList.remove("err", "warn");
      if (last === null) { hint.textContent = initial; }
      else if (km === null) { hint.textContent = initial; hint.classList.add("warn"); }
      else if (km >= last) {
        hint.textContent = "+" + (km - last).toLocaleString("en-US", { maximumFractionDigits: 1 }) +
          "\u00a0km since the last recorded reading (" + (/\((.*)\)/.exec(hint.dataset.lastText) || [0, "initial"])[1] + ").";
      } else {
        hint.textContent = "Lower than the last recorded reading, " + hint.dataset.lastText.replace(/^([\d.,]+)/, "$1\u00a0km") + ". Check the number.";
        hint.classList.add("err");
      }
      save.disabled = !(title.value.trim() && number(amount.value) !== null);
    }
    groups.forEach(function (group) {
      group.querySelectorAll(".chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
          title.value = chip.getAttribute("data-title");
          showChips(); update();
        });
      });
    });
    types.forEach(function (type) { type.addEventListener("change", showChips); });
    [title, amount, odo].forEach(function (input) { input.addEventListener("input", function () { showChips(); update(); }); });
    day.addEventListener("change", function () { chipDate(day, form.querySelector("[data-quick-date]")); });
    showChips(); update();
  }

  /* ---------- quick add: odometer hint, Save enabled when complete, date chip ---------- */
  function bindQuick(root) {
    var form = root.querySelector("form.quick");
    if (!form || form.dataset.bound) { return; }
    form.dataset.bound = "1";
    if (form.dataset.quickKind) { bindQuickEntry(form); return; }
    var odo = form.querySelector("#i-odometer_km"), litres = form.querySelector("#i-litres");
    var total = form.querySelector("#i-total"), save = form.querySelector("[data-quick-save]");
    var hint = form.querySelector("[data-quick-hint]"), day = form.querySelector("#i-date");
    var chip = form.querySelector("[data-quick-date]");
    var last = hint.dataset.lastKm === "" ? null : parseFloat(hint.dataset.lastKm);
    var initial = hint.textContent.trim();
    function update() {
      var km = number(odo.value);
      hint.classList.remove("err");
      if (km !== null && last !== null) {
        var diff = km - last;
        if (diff >= 0) {
          hint.textContent = "+" + diff.toLocaleString("en-US", { maximumFractionDigits: 1 }) + "\u00a0km since the last refuelling";
        } else {
          hint.textContent = "Lower than the last odometer (" + hint.dataset.lastText + "\u00a0km). Check the number.";
          hint.classList.add("err");
        }
      } else { hint.textContent = initial; }
      save.disabled = !(km !== null && number(litres.value) > 0 && number(total.value) > 0);
    }
    function dateText() { chipDate(day, chip); }
    [odo, litres, total, form.querySelector("#i-price_per_litre")].forEach(function (input) {
      input.addEventListener("input", update);
    });
    day.addEventListener("change", dateText);
    update();
  }

  /* A snackbar goes away by itself; the Undo button stays a plain form post. */
  document.querySelectorAll("[data-snackbar]").forEach(function (bar) {
    setTimeout(function () { bar.remove(); }, 6000);
  });

  bindOdometerHint(document);
  bindFuelType(document);
  bindQuick(document);
  bindCalc(document);
  bindStationSelect(document);
  bindRevealSelect(document);
  bindCopy(document);
  drawCharts();
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawCharts, 150);
  });
})();
