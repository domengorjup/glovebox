## Decisions

- **Last known odometer** of a vehicle on a date: the highest entered reading (refuels, and expenses whose odometer is not estimated) dated on or before that date; the vehicle's initial odometer if it is higher or nothing else exists. Estimated values are skipped, so an estimate never feeds the next estimate and never ratchets upward.
- **Only the web form estimates.** Service functions, the API and imports store what they are given. Imports never invent odometers.
- **Warning after save** is a one-time notice kept in the `setting` table (key `flash`) and shown, then cleared, on the next Timeline page. The page script reloads the current page after a dialog save and ignores the redirect target, so a query parameter would be lost.
- **Stats.** Estimated odometers are excluded from the odometer span (`_distance_driven`) and from `last_odometer_km`. Real readings alone decide the distance. Segments and consumption use refuels only and are unaffected.
- **Editing an estimated expense** shows the field empty (the stored value is not a typed one); saving it empty re-estimates, typing a value stores it as a real reading.
- **Hint follows the form.** The form embeds, per vehicle, the points where its last known odometer rises (`odometer_steps`: date and km, running maximum of real readings). A small handler in `app.js` picks the last point on or before the chosen date when the vehicle or date changes. Without JavaScript the server-rendered hint (form's vehicle, its date) stays. The saved value and the warning always use the submitted vehicle and date.
