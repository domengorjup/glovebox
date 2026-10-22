# Gas stations

Stations are created when you add a refuelling ("New station") or when you import a file. Manage them under **Manage → Gas stations**.

![Gas stations](../assets/screenshots/stations-desktop-light.png)

## Brands

A station has a name and an optional brand, for example station "Petrol Tržaška" with brand "Petrol". Statistics can group by brand to compare companies.

Brands are set **by hand only**. Glovebox never guesses a brand from a name. You can set a brand on one station, or tick several stations, type a brand and press **Set brand** to set it for all of them at once (**Clear brand** removes it).

## Renaming

Open a station to change its name, location or brand.

## Merging duplicates

Imports and typing errors often create duplicates ("PETROL Trzaska" and "Petrol Tržaška"). Use the **Merge duplicates** section at the bottom of the page: pick the duplicate under *Merge this station...* and the one to keep under *...into this one*, then press **Merge**. All refuellings of the duplicate move to the station you keep, and the duplicate is removed.

## Deleting a station

Open a station and press **Delete**. If no refuelling uses it, you only confirm. If refuellings use it, the dialog tells you how many and asks which station they move to. The list shows the other stations, those with the same brand first, then by name. The default is **No station**, which leaves those refuellings without a station. The refuellings are moved and the station is removed in one step, and this cannot be undone.
