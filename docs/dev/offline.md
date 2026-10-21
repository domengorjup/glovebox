# Offline use (draft)

Status: ideas only, nothing is implemented.

## The case to cover

The typical moment to log a refuel is at the pump: on a phone, often with poor mobile data, sometimes with Home Assistant unreachable. Viewing statistics offline matters much less than not losing a new entry.

So the minimum is: **capture a refuel or expense while offline and send it once Glovebox is reachable again**, without duplicates.

## Constraints

- The UI is served by the add-on through HA Ingress (`/api/hassio_ingress/<token>/`). If HA Core is down or unreachable, nothing under that path loads.
- Pages are rendered on the server, and forms post to the server. There is no client-side data store today.
- Phones mostly reach Glovebox through the HA companion app (a WebView) or a browser.

## Options to evaluate

1. **Rely on what HA and the companion app already offer.** Check what the companion app does when the server is unreachable, and whether actions or notifications can be queued. Preferred if it exists.
2. **Browser-side outbox.** A service worker caches the add form, and new entries are stored locally (IndexedDB) and posted when the server answers again. Each entry carries a client-generated id so a resend is not duplicated. Open question: whether a service worker works under the Ingress path, given that the Ingress token in the URL can change between sessions.
3. **Low-tech fallback.** Write entries down anywhere (e.g. a phone note or spreadsheet in the standard CSV format) and import them later. This works today with no code; the importer's duplicate detection already prevents double entries.

## Open questions

- Is offline *viewing* needed at all, or only offline *capture*?
- How are conflicts handled if the same entry is edited on two devices? (Possibly out of scope: entries are append-only in practice.)
