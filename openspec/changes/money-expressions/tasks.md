## 1. Server
- [x] 1.1 `web/formatting.py`: `evaluate_expression`, `parse_money` (D1, D2); use it for refuel `total` and `price_per_litre` and expense `amount`. Parser unit tests (precedence, comma, `=`, spaces, division by zero, garbage).
- [x] 1.2 Form tests in `tests/test_money_expressions.py`: refuel total and price (quick page) and expense amount saved as sums; bad sum shows the field error.

## 2. Page script
- [x] 2.1 `web/static/app.js`: evaluate on change, replace the text, `.invalid` on error, calculation and quick Save state use evaluated values (D3). Headless check on the quick refuel page.

## 3. Docs and checks
- [x] 3.1 `docs/user/records.md` sentence; `mkdocs build --strict`.
- [x] 3.2 Tests of the touched files green; `openspec validate money-expressions --strict`.
- [x] 3.3 At release: CHANGELOG entry (cost fields accept sums such as =12.50+3).
