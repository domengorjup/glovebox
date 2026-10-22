## 1. Behaviour
- [x] 1.1 `services/periods.py`: period ranges and comparison ranges (same days, clamped at month end)
- [x] 1.2 Period stored per vehicle and for the combined summary (`setting` table); `POST /preferences/period`
- [x] 1.3 Timeline cards follow the period; hints show the range; cost comparison; empty-period texts
- [x] 1.4 Period chip with popover (desktop) and bottom sheet (phone), form post without JavaScript
- [x] 1.5 Phone: Customise as icon-only button

## 2. Checks
- [x] 2.1 Unit tests for ranges and comparison; web and e2e tests through the real forms
- [x] 2.2 Docs (`timeline.md`, `design.md`), `openspec validate`, full test run, docs build, `formatdocs --check`
- [x] 2.3 Screenshots (phone and desktop, light and dark)
