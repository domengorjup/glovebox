## Decisions

- **Field names:** `model_year` (not `year`, which reads as a date), `insurance_valid_until` and `registration_valid_until` (dates). Columns carry the same names in the database and in `vehicles.csv`.
- **Free text for engine and tyre size:** formats differ too much between markets and cars to be worth structured fields.
- **Validation:** `model_year` is a whole number from 1886 to next year; both dates are ISO dates. Empty means unset. A VIN is trimmed and upper-cased but not checked (older and non-EU vehicles have other formats).
- **Import is lenient, as for the odometer:** an invalid value in `vehicles.csv` is reported as a row error and the vehicle is imported without that value.
- **Copying the VIN:** a button in the form. It uses the clipboard API where it is available and selects the text and copies it otherwise (HA over plain HTTP has no clipboard API). Without JavaScript the button is hidden; the text can be selected by hand.
- **Existing expense coverage dates** (insurance/registration expenses) are untouched. The new dates are independent; a later reminders feature may offer to link them.
