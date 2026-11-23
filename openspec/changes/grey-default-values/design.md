## Context

Placeholders are the app's normal grey hint (`.field input::placeholder`). Both defaults must also work without JavaScript, so the server decides what is stored.

## Decisions

### D1. "Same fuel type" is the vehicle
The fuel type belongs to the vehicle, not to a refuel (no column on `refuel`). "Last refuel of the same vehicle, preferring the same fuel type" therefore reduces to the last refuel of the chosen vehicle (newest by date, odometer, id, as the Timeline orders them). A vehicle without a refuel shows no grey price (placeholder `0.000`). Changing the vehicle on the full form swaps the grey price; the quick page changes vehicle by reloading.

### D2. Grey price rule
Applies to add forms only (not edit). The server, on save of a new refuel, with the price field empty and exactly one of litres / total given, takes the vehicle's last price as the price; the other figure is derived as today (and marked derived). With both litres and total given the price is derived from them as today. With neither, the existing error stays. The price is stored as a normal (not derived) figure when taken from the default; this is the same as a typed price.

The page follows the same rule: typing litres or total while price and the other field are empty (or calculated) fills the other field from the grey price and shows it as calculated; typing both calculates the price. The default is read from a per-vehicle map in a `data-` attribute of the price group. The quick page no longer marks litres and total as required when a grey price exists (one of them is enough); without a grey price both stay required.

### D3. Odometer
The server fills nothing into the field. On save of a new service or expense (not edit) an empty odometer becomes the last known odometer of the vehicle on the entry date (`last_known_odometer`), with `odometer_estimated` false; no earlier reading stores no odometer. The 422 re-render keeps what was typed; the placeholder is set again. The page follows vehicle and date changes by setting the placeholder from `odometer_steps`, and the hint keeps its three states, computed from the typed value, or the placeholder reading when empty.

### D4. Style
Existing placeholder colour (primary text colour at 60 % opacity) is kept if it is visibly lighter than typed text in light and dark; otherwise a rule at the end of `app.css`.
