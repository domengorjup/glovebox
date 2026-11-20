## Context

The forms post text; `web/formatting.py::parse_decimal` turns it into a `Decimal` (comma accepted), then `to_scaled_int` rounds half up to cents or thousandths. The refuel form has a client-side two-of-three calculation.

This follows the design of the sibling app Cekar (its uncommitted change, `src/cekar/web/formatting.py` and `specs/expenses`, checked 2026-11-20): same grammar, exact `Fraction` evaluation, same messages. Differences: Cekar's page script does not evaluate; ours also evaluates on change in the browser (D3), because the refuel form calculates the third figure live. Our plain numbers keep their own rules (no decimal limit as before); Cekar's two-decimal limit does not apply here.

## Goals / Non-Goals

**Goals:** a plain number keeps working exactly as before; the same grammar on server and client; no `eval`.

**Non-Goals:** functions, percentages, expressions in litres or odometer, evaluating when stored data is imported.

## Decisions

### D1. Grammar
`["="] expr`, `expr = term {("+"|"-") term}`, `term = unary {("*"|"/") unary}`, `unary = "-" unary | "(" expr ")" | number`. Number = digits with an optional decimal comma or point (`.5` accepted). All spaces are ignored (so `1 2` reads as 12, as in Cekar). At most 200 characters, which also bounds the recursion. Exponent notation (`1e3`) works as a plain number only. A result of zero or below passes the same checks as a typed one (the records service decides).

### D2. Server
`parse_money` first tries `parse_decimal`, so every plain value gives the same result as before. Only when that fails does `evaluate_expression` run: a recursive-descent evaluator over `fractions.Fraction` (exact, no `eval`). The result is turned into a `Decimal` and rounded half up by the existing `to_scaled_int` (cents, or thousandths for price per litre). Errors raise `ValueError("<Field>: Not a valid calculation.")` or `("<Field>: Can't divide by zero.")`, which the forms already show as the field error with the typed text kept.

### D3. Client
`app.js` evaluates the same grammar with floats, on `change` of `input[name=total]`, `[name=price_per_litre]` and `[name=amount]`, only when the text has an operator or starts with `=`. The result replaces the text (2 decimals, 3 for price per litre) and an `input` event is fired so the calculation and the Save-button state follow. Invalid text stays, the field gets the existing `.invalid` style, cleared on the next keystroke. The calculation and the quick pages' Save check read these fields through the evaluator, so a half-typed `12+` counts as empty rather than as 12. Same grammar, including parentheses and unary minus. The server stays the authority: a form posted without the script is evaluated there.

### D4. Keyboard
`inputmode="decimal"` stays. A phone keypad may lack `+ - * /`; the user then switches keyboard. Accepted trade-off (user decision).

## Risks / Trade-offs

- Float arithmetic in the browser can differ from the exact server result in the last digit; the result is rounded to the field's decimals and the server re-evaluates exactly on save.
- A decimal comma next to a thousands comma is ambiguous; as before, a comma is always a decimal mark.
