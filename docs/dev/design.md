# Design language

The web UI follows Home Assistant (HA) and Material conventions, so that it looks at home inside the HA sidebar. This page lists the rules, the tokens and every reusable element. Read it before adding anything to `src/glovebox/web/templates/` or `static/app.css`.

## Principles

1. **Follow HA / Material.** If HA has a standard pattern (sub-page header with a back arrow, filled text fields, a floating add button, a bottom sheet on phones), use it in the same shape.
2. **Own elements only when much simpler.** Build a custom element only if it is clearly simpler than the standard one. Say why in the commit.
3. **Reuse before adding.** Look through this page first. A new class needs a new entry here; a near-duplicate of an existing element gets merged instead.
4. **No plain text links for in-app navigation.** Navigate with buttons, icon buttons, list rows, tabs, chips or segmented choices. Plain links are only for external or documentation links inside body text.
5. **Dialogs are pages first.** Every dialog is a normal server-rendered page; `app.js` only fetches it into `#overlay`. Everything works without JavaScript.
6. **Numbers never wrap.** Join a number and its unit with a non-breaking space (`with_unit`, `money`) and use `white-space: nowrap` on values.
7. **Every URL goes through `url(request, ...)`** so Ingress prefixes work.

## Tokens

All colours, radii and spacing are CSS custom properties with the names HA uses (`--primary-color`, `--card-background-color`, `--divider-color`, ...). `app.css` holds light and dark defaults; `theme.js` replaces them with the live HA theme when the page runs inside HA. Never hard-code a colour; use a variable.

| Group | Tokens |
|---|---|
| Colour | `--primary-color`, `--text-primary-color`, `--primary-text-color`, `--secondary-text-color`, `--divider-color`, `--card-background-color`, `--primary-background-color`, `--secondary-background-color`, `--error-color`, `--success-color`, `--warning-color`, `--input-fill-color`, `--input-idle-line-color`, `--shadow-color` |
| Chart colours | `--color-1` to `--color-5` (fuel, service, insurance, registration, other) |
| Spacing | `--ha-space-1` 4px, `-2` 8px, `-3` 12px, `-4` 16px, `-5` 20px, `-6` 24px, `-8` 32px |
| Radius | `--ha-border-radius-sm` 4px, `-md` 8px, `-lg` 12px (cards), `-xl` 16px, `-pill` (buttons, chips) |
| Type | Font `--ha-font-family-body` (from HA when available, else system sans-serif). Body 14px; page title 20px; section heading 14px (secondary colour); list title 15px; detail 13px; small 12px; stat value 26px (22px phone, 20px compact) |
| Breakpoint | One: phone below 700px (`@media (max-width: 699px)`). Phone gets the bottom nav, full-screen dialogs and two-column card grids. Content width is capped at 880px |
| Header | `--header-height` 56px |

## Layout skeleton

Every page extends `base.html` (or `partial.html` when a dialog is fetched). `main` has bottom padding so the floating button and the phone bottom nav never cover content.

```jinja
{% extends layout %}
{% block title %}Name - Glovebox{% endblock %}
{% block content %}
  ...
{% endblock %}
```

Section headings are plain `<h2>`; a heading with an action on the right uses `.summary-head` (`<h2>` plus a button).

## Standard elements

### App bar with vehicle select

Always visible. Brand, a vehicle dropdown (active vehicles plus "All vehicles"), and on desktop the tabs. The select posts to `/preferences/vehicle` and submits on change (`data-autosubmit`); a "Show" button appears without JavaScript. The `data-autosubmit` handler lives in `theme.js` (loaded in the head), not in the deferred `app.js`, so a choice made while the page script is still loading is not lost. Archived vehicles are never listed. It lives in `base.html`; do not copy it.

### Version label

`span.app-version` at the right end of the app bar, after `span.spacer`: "v" plus the installed package version, 12px, secondary text colour. The value is the Jinja global `app_version`, read once from `importlib.metadata` in `templating.py`; never hard-code it. On phones the spacer is hidden so the vehicle select keeps its width. Written once in `base.html`.

### Download button inside a dialog

A dialog form is submitted with `fetch`, which would swallow a file. A button that downloads (delete-vehicle confirm: "Download full backup") is a secondary `.btn.with-icon` with `formaction` pointing at the download endpoint and the attribute `data-download`; `app.js` then lets the browser submit natively and the dialog stays open.

### Tabs and bottom nav

Desktop: `.tabs` with `a.tab` (active tab has `.active`). Phone: `.bottom-nav` with icon pills. Both are written once in `base.html` and must list the same three sections: Timeline, Stats, Manage. Add a section there, nowhere else.

### Sub-page header with back button

HA's standard sub-page header: a round icon button with an arrow on the same row as the title, left of it. Use it on every page that has a parent (Manage sub-pages, import preview). Top-level pages (Timeline, Stats, Manage) have a plain `<h1>` in `.page-title`.

```jinja
{{ page_head(request, 'Gas stations') }}                         {# parent: Manage #}
{{ page_head(request, 'Import preview', '/import', 'Import') }}  {# parent: Import #}
```

It renders `.page-head` with `a.icon-btn` (`aria-label="Back to <parent>"`, 40px target, hover and focus background, secondary text colour) and `<h1>`. Dialogs do not use it; they have a close button (see Dialog).

### Summary cards

A grid of stat cards: label, big value with a small unit, and a hint line. `.summary-grid` is the only stat grid; add `.compact` for denser cards (Stats KPIs, per-vehicle summaries). Values come already formatted from Python so numbers never wrap.

```html
<div class="summary-grid">
  <div class="card stat" data-card="cost_month">
    <div class="label">Cost</div>
    <div class="value">90.88&nbsp;&euro;</div>
    <div class="hint">-53.48&nbsp;&euro; vs September</div>
  </div>
</div>
```

On the Timeline the user picks the cards (and in "All vehicles" the summary groups) in the **Customise** popover (`details.customise` with `form.popover`). On desktop it is a small dropdown; on phones it is a bottom sheet (fixed to the bottom, rounded top, dim backdrop made with a box-shadow, `.pop-head` with the title and a Done button `[data-close-customise]`, rows at least 48px). Tapping the backdrop, Done or Escape closes it. Choices are stored server-side; `data-card` and `data-summary` let `app.js` apply them live.

### List card and rows

A card containing rows. A row is a whole-row link or button with a round badge, title, detail lines, and either an amount/date block (`.side`) or a chevron (`.chev`). Use it for timeline entries, vehicles and Manage entries. Rows on the Timeline are grouped under `.month-head`.

```html
<div class="card list-card">
  <a class="row" href="..." data-dialog>
    <span class="badge t-refuel">{{ icon('gas-station', 22) }}</span>
    <span class="body"><span class="title">Refuelling</span><span class="detail">35.44 L</span></span>
    <span class="side"><span class="amount">55.89 &euro;</span><span class="date">14 Oct</span></span>
  </a>
</div>
```

A row whose text must be read in full (presets) wraps its note with `.detail.wrap`; the row then holds an `a.row-link` plus icon buttons, and the link opens a detail dialog.

Badge colours: `t-refuel`, `t-service`, `t-expense`. A row that also needs a checkbox (stations, export vehicles) is a `.row` containing `label.pick` and `a.row-link`; do not add other row variants.

### Period chip

A small chip in a summary heading (`details.customise.period` > `summary.chip.period-chip` with a `menu-down` icon) that opens a picker. The picker reuses the Customise popover: a small dropdown under the chip on desktop and the same bottom sheet on phones (title "Period", Done, 48px rows). It is a form (`form.popover.period-pop`, `POST /preferences/period`) with a radio per fixed period; picking one submits at once (`data-autosubmit`, skipped for `custom`). "Custom range" reveals `.pop-dates` (From / To `.field`s) and an Apply button; without JavaScript the dates and Apply are always shown. A custom range makes the chip `.active` and shows the dates as its label. Put the chip on the right of a heading row: `.summary-head` > `.head-tools` for the main summary, `.veh-head-row` for the per-vehicle ones. On phones the Customise button is icon-only (`.cust-txt` hidden) so heading, chip and button fit one row.

```html
<details class="customise period"><summary class="chip period-chip">Last 12 months ...icon</summary>
  <form class="popover period-pop" method="post" action=".../preferences/period"> ... </form></details>
```

### Filter chips

Single-choice filter for a list (Timeline type). Links, so the filter lives in the URL.

```html
<div class="chips"><a class="chip active" href="...">All</a><a class="chip" href="...">Refuelling</a></div>
```

### Segmented choice

For a small set of mutually exclusive view options inside a form or filter bar (Stats What / When / Costs, price table By station / By brand, expense type). Use `a` for URL-driven choices, `label` with a radio input for form fields. Use chips instead when the choice filters a list on its own.

```html
<div class="seg"><a class="active" href="...">Spread</a><a href="...">As paid</a></div>
```

The Stats filter bar is a `.card.filter-bar` of `.filter-line` rows (`span.lbl` plus a `.seg` or fields).

### Buttons

One `.btn` base (pill, text style). Variants:

| Kind | Markup | Use |
|---|---|---|
| Primary (filled) | `.btn.primary` | The one main action of a card or dialog (Save, Add vehicle) |
| Secondary (outlined) | `.btn.outline` | Other real actions (Undo, Clear brand) |
| Text | `.btn` | Cancel, low-emphasis actions, Customise (`.btn.with-icon` adds an icon and compact padding) |
| Icon | `a.icon-btn` or `button.icon-btn` | Back and close; always has `aria-label` |
| Danger | `.btn.danger` (text, red) and `.btn.danger-fill` | Delete; the filled one only on the final confirmation |

```html
<a class="btn primary" href="..." data-dialog>{{ icon('plus', 18) }}Add vehicle</a>
```

Any button that destroys data carries `data-confirm="Question?"` (browser confirm) or opens a confirm dialog. `{{ post_button(request, path, label, confirm_text) }}` renders a small outlined POST button.

### Floating button and chooser

The round `+` (`a.fab`, `data-dialog`) appears on the Timeline only. It opens `/add`, a bottom sheet on phones and a small dialog on desktop, listing three `a.choice` rows: Refuelling, Service, Expense. The category mapping is fixed: Service is maintenance; Expense is insurance, registration or other.

Refuelling opens the quick-add page (`/quick`, see below), not the full form.

### Quick-add page

`refuels/quick.html`, a `dialog_page` form (full screen on phones, 460px dialog on desktop) with a sticky foot. Everything works without JavaScript: the reveals are CSS-only (`:has()` on a hidden checkbox or radio), the script only adds the live hint, the enabled state of Save and the date text. New classes:

- `.qgroup` (stack of a field and its hint), `.qlabel` (small label above chips), `.qhint` (help line under the odometer; `.err` turns it red).
- `.field.big`: filled field with a 28px value (odometer, litres, total). The `field` macro takes `big=True` and `autofocus=True`.
- `.qchips`: chips of 40px height. Choice chips are `label.chip` around a hidden radio (`.qchips.stations`: two columns, name ellipsised, selected = tinted). `.qmore` holds two toggle chips (date, More) that tick the hidden `.qtoggle` checkbox after them and reveal `.qdate-panel` / `.qextra`; `.qother` is the station select shown by the "Other" radio.
- `.big-btn`: full-width 56px primary button in `.qfoot`. A disabled `.btn.primary` is grey.
- The vehicle choice is a `.seg.type-seg` of links (`?vehicle=`) and appears only with more than one active vehicle.
- `.field label .fuel-type`: the vehicle's fuel type after the Litres label ("Litres · Diesel"), read-only, medium weight; nothing when the vehicle has none. Quick form: server-rendered, follows `?vehicle=`. Full form: also updated by `app.js` (`bindFuelType`) from `data-fuel-types` JSON on the span when the Vehicle select changes.
- `.field.computed`: the value the page script calculated (any two of litres, price per litre, total) is drawn in the primary colour; typing in it removes the mark. The full refuelling form uses it too.

**Quick service and expense** (`expenses/quick.html`, `/quick-service`, `/quick-expense`) use the same classes. They add: a title field with `.qchips.titles` chips under it (script-only: hidden in the markup, shown and wired by `app.js`; a chip fills the title; service starts with a fixed "Regular service", then the vehicle's recent titles, at most 4; expense shows the chips of the chosen type); the amount as a `.field.big`; an odometer field that starts empty with the last known reading as its placeholder and as the hint ("Last: 75,892 km on 9 Oct"); `.qhint.warn` (orange) while it is empty, "+N km since…" when higher, `.qhint.err` when lower. Left empty, the last reading is saved as an estimate (server side, no script needed). The full add forms show the same placeholder (updated with vehicle and date); edit forms do not. The expense type is the `.seg.type-seg` of radios; coverage dates and notes sit under More.

**Deep link from the Android shortcut.** Home Assistant opens an add-on panel at its start page, but it serves `/<panel>/<anything>` as the same panel and the iframe can read the parent URL (same origin). `theme.js` therefore checks `window.parent.location.pathname` for `/<panel>/quick`, `/quick-service` or `/quick-expense`; it first rewrites the parent URL to `/<panel>` with `history.replaceState` (no popstate, so HA's router does not react, and a reload or Back does not loop) and then opens that page in the iframe, below the Ingress base taken from its own script URL. Anything unreadable (standalone, cross-origin) is ignored. Tested on the test VM only for the routing (the subpath serves the panel and the iframe sees it); the redirect itself is tested with a stand-in parent page.

### Reminder rows and the Due soon card

`reminder_rows(request, rows, next_path, open=True)` in `_macros.html` renders reminders as list rows: a `.row` holding an `a.row-link` (category badge `t-service` for Service, `t-expense` for the others, title, vehicle tag in the all-vehicles view, a `.detail` with "Due 5 Nov 2026 · in 13 days", and a `.detail.wrap` line with the calendar message when the reminder is not synced) and, for open reminders, a form with a primary-coloured check `icon-btn` (Done). The detail line gets `.overdue` (error colour) when the due date has passed. Done reminders have a chevron instead of the button. The link opens the reminder dialog with `?next=` so that it works without JavaScript.

The Timeline "Due soon" card is a `.card.list-card.due-card` whose first child is `.due-head` (the `h2` and a text `.btn.with-icon` "All reminders"); rows follow. It sits above the summaries and is not rendered when nothing is due. The Reminders page lists open reminders under `.summary-head` ("Open (N)" and a primary "Add reminder") and the done ones in a `details.archived`.

### Calendar setting card

On the Reminders page (add-on mode only): a `form.card.card-pad.stack` with `.alert.warning` lines for problems, a `select` (autosubmit; "None" plus every calendar that can create events, each labelled with what it can do, plus the stored choice marked "not available" when it is gone), a `.help` line, optional `.alert.warning` for events left behind, and an `.actions` row with an outlined "Sync now" (`.btn.outline.with-icon`). In standalone mode the card is replaced by one `.help.flush` sentence in a `.card.card-pad`.

### Remind me switch

`remind_switch(name, label, checked, days)` in `_macros.html`: a `.remind-block` with a `switch` and, under it, `.remind-days` (a "Notify ... days before" `.field` named `<name>_days`). The days field is shown only while the switch is on, by CSS `:has()`, so it works without JavaScript. Used on the add-expense forms (full, and under More on the quick one) and next to the two valid-until dates in the vehicle dialog. On an expense that already exists the dialog has an outlined "Remind me" button (`.btn.outline.with-icon`, bell icon) that opens the reminder dialog pre-filled.

### Buttons inside a dialog body

A row of secondary actions in the body of a form dialog (reminder dialog: "Download .ics", "Mark done" or "Reopen", "Sync now"; expense dialog: "Remind me") is `.actions` inside `.dialog-body`, left-aligned. A file download is a plain `a.btn.outline.with-icon` with the `download` attribute (a GET), not a `data-download` submit button.

### Snackbar

Material snackbar for the result of an action that is already done and can be reversed ("Refuel saved · 38.4 L · 64.90 € · 8.8 L/100 km", Undo). Used by the quick refuelling, service and expense pages. Server-rendered on the page the user lands on, as `form.snackbar[data-snackbar]` with `.snackbar-text` and a text `.btn` that posts the undo, so it works without JavaScript; `app.js` removes it after 6 seconds. Fixed at the bottom (left on desktop, full width above the bottom nav on phones); while it is shown on a phone the floating button moves up (`body:has(.snackbar) .fab`) so they never overlap. The data comes from `preferences.set_flash` (`kind="refuel_saved"`), shown once. Use it for undoable results; failures stay `.alert.error` or `toast`.

### Dialog and confirm

All forms open as a dialog: `.scrim` (click to close) containing `form.dialog.form` with `.dialog-head`, `.dialog-body` and `.dialog-foot`. The head has a close `icon-btn` (a real link, so it works without JavaScript). On phones the form dialog is full screen. A confirmation is `form.dialog.confirm` with an `h3`, one paragraph, optionally one `.field` (select) when the user must choose before confirming (delete station: where its refuellings move), and a foot with Cancel and the action.

```jinja
<div class="scrim" data-scrim>
<form class="dialog form" method="post" role="dialog" aria-label="Edit station" action="{{ url(request, '/stations/1/edit') }}">
  {{ dialog_head(request, 'Edit station', '/stations') }}
  <div class="dialog-body">{{ messages(errors) }} ...fields...</div>
  <div class="dialog-foot">
    <a class="btn" href="{{ url(request, '/stations') }}" data-close>Cancel</a>
    <button type="submit" class="btn primary">Save</button>
  </div>
</form>
</div>
```

Dialog pages set `{% set dialog_page = true %}` so the page behind them gets no FAB.

### Messages

`{{ messages(errors, warnings) }}` renders `.alert.error` and `.alert.warning` blocks at the top of a form or page. `.alert.success` reports the result of a finished action on the page it returns to (the import result: counts plus an outlined Undo button on the right, via `post_button`). Use it instead of a toast when the user needs to see what happened or reverse it. A field-level hint is `.help` (`.help.err` for an error). A notice that must survive a redirect (the odometer warning after saving an expense) is stored once with `preferences.set_flash` and shown by the Timeline as `.alert.warning`, because the page script reloads the page and ignores the redirect target. An estimated odometer in a list row is written as `≈ 104,163 km` in the `.detail` line; it needs no extra element.

### Form fields, select and switch

Use the macros from `_macros.html`; they produce HA's filled text field (label above, underline, optional unit suffix).

```jinja
{{ field('Odometer', 'odometer_km', f.odometer_km, suffix='km', inputmode='decimal', required=True) }}
{{ select('Fuel type', 'fuel_type', options, selected) }}
{{ vehicle_select(vehicles, f.vehicle_id) }}            {# every add/edit form #}
{{ switch('is_full', 'Full tank', 'Needed to work out consumption', f.is_full) }}
{{ textarea('Notes', 'notes', f.notes) }}
```

Lay fields out with `.grid2` / `.grid3` inside `.dialog-body`; plain forms on a page use `.card.card-pad.stack`. Currency and units are suffixes, not part of the label.

### Collapsible section

A native `<details>` with a `<summary>`; no custom widget. Used for the archived vehicles (`details.archived`) and the Customise popover.

```html
<details class="archived"><summary>Archived (1)</summary> ...list card... </details>
```

### Field with a copy button

A text field whose value is often copied (the VIN) gets `copy=True` in the `field` macro: `.field.has-copy` with a `button.icon-btn.field-copy[data-copy="i-<name>"]` inside the field, right-aligned. The button is `hidden` in the markup and `app.js` (`bindCopy`) shows it, since without JavaScript it would do nothing. It uses the clipboard API and falls back to `execCommand("copy")` on plain HTTP, then shows a toast.

### Tables and charts

`table.tbl` in `.card.card-pad.table-scroll` for the price table; numeric cells have `.num`, columns that are dropped on phones have `.wide`. Charts are inline SVG drawn by `app.js` from the `#chart-data` JSON into `[data-chart]` inside `.card.chart-card`, with a `.legend` below (swatches `.swatch-<key>`).

### Footer links (Manage page)

`div.manage-links` below the last card on Manage: centred, holds icon-only `a.icon-btn` links (`aria-label` and `title`, `target="_blank" rel="noopener"` because the app runs in the Ingress iframe and GitHub refuses to load in a frame). Currently GitHub (`github`) and Documentation (`book-open-variant`).

```html
<div class="manage-links">
  <a class="icon-btn" href="https://github.com/domengorjup/glovebox" target="_blank" rel="noopener" aria-label="Glovebox on GitHub" title="Glovebox on GitHub">{{ icon('github', 24) }}</a>
</div>
```

### Toast

For a result the user can undo use the Snackbar above. `toast(message)` in `app.js` shows a short `.toast` at the bottom of the screen for about three seconds. Use it only to report a background action that failed (for example saving the card choice); successful actions reload the page and need no toast.

### Empty state

`<div class="empty">No entries</div>` inside the place where the content would be (inside a `.card` when a card is expected). One short sentence; if the user can fix it, add a primary button under it.

### Import mapping, export customise and preset rows

These pages reuse existing elements; the only new classes are listed under "Mapping row layout".

- **Mapping field** (import mapping): a `.map-item` inside one `.card.card-pad.map-list` (items separated by hairlines): a `.grid2.map-row` of two filled fields (source select, constant value) and a `details.map-opts` "Options" block that starts with the description as `.help.flush`, then the value map, true/false values, missing values and default. The select's first options are "Not mapped" and "Constant value", then the file's headers. The label is the human name of the field followed by the standard key in `span.key` (small monospace secondary text), with `*` for a required field. The description is also the label's `title`.
- **Folded settings card** (`details.card.fold`, import mapping: File, Value formats; also "More details" in the vehicle dialog, with "N filled" as its summary): a card whose summary row shows a title (`.fold-title`), a one-line summary of the current values (`.fold-sum`, right-aligned, wraps) and a chevron; the body is `.fold-body.stack`. Collapsed by default so the mapping page is short on a phone; the inputs stay in the form and are submitted. It opens by itself when the file could not be read, a file setting is explicit or there is an error. Use it for any settings block that is correct most of the time.
- **Preset steps** (`ol.steps`): a small numbered list in secondary text with a primary-coloured number, directly under the preset select and its one-line note. Its items come from the preset's `steps` (about 8 words each, at most 5). Use it for short "what to do" lists inside a card.
- **New vehicle choice** (import preview): the vehicle select ends with "New vehicle..."; a `.new-vehicle` block with a filled name field follows and is shown only while that option is selected (`data-reveal-select` on the select, `data-reveal="new"` on the block; without JavaScript it stays visible). The select and the name field carry `data-autosubmit` (the select with `data-autosubmit-skip="new"`, since "New vehicle..." must wait for the name), so the preview updates in one step.
- **Import review** (the page after the upload): one `form.stack` with a `.card.card-pad.stack` holding the preset select (`data-autosubmit`), the `ol.steps`, any questions (radio groups with `data-autosubmit`) and the vehicle choice; below it a `.actions` row with an outlined "Adjust mapping" and the primary "Import now" (the Import button must be visible without scrolling on a 390x844 phone for the common case, so it comes before the counts); then the one-row counts card. The default first submit button is the harmless "Update" (`no-js-only`). The mapping page carries a primary "Back to review" at the top (`.actions.top`) and at the bottom.
- **Next section** (import result): after the `.alert.success`, an `.alert.next-section` (same flex layout as `.alert.success`, neutral border) names the remaining sections and holds a primary `a.btn.primary.with-icon` "Import next section: <section>".
- **Mapping row layout** (new class `map-row` on the `.grid2`, `map-const` on the constant field): the constant-value field is hidden until "Constant value" is chosen in the source select (CSS `:has()`, no script), so a row is one select and the Options link on a phone. Fields that are mapped, have options or are required come first; the others sit in a collapsed "Fields not mapped (N)" block (`details.more-fields`), still in the form.
- **Step state**: mapping, review and confirm are one `form.stack`; the edited mapping travels as hidden fields (`base_toml`, `selected_preset`, `preset_id`) plus the mapping inputs. Buttons switch the step with `formaction`; the default (first) submit button must be the harmless one.
- **Questions**: a `.filter-line` with `span.lbl` and a `.seg` of radio labels.
- **Row errors**: `table.tbl` in `.card.card-pad.table-scroll`; the heading gives the total and how many are shown.
- **Vehicle picker** (export): `.list-card` rows with `label.pick` and a `label.body` for the name.
- **Preset rows**: `.list-card` rows with a badge, name, status and note lines, a download `icon-btn` and, for own presets, a `post_button` Delete.

## Checklist for a new page or element

1. Does an element above already do this? Use it.
2. Standard HA / Material pattern exists? Follow it.
3. In-app navigation uses a button, icon button, row, tab, chip or segmented choice, never a bare link.
4. Colours, spacing and radii are variables; works in light and dark and at 390px width.
5. Numbers and units do not wrap; nothing is covered by the floating button.
6. New class or macro? Add it to this page, and add a test when it carries behaviour.
