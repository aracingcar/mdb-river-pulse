# Murray–Darling River Pulse

An interactive river map inspired by [mapped.earth’s River Pulse](https://mapped.earth/river-pulse/), using Bureau of Meteorology Water Data Online observations and OpenStreetMap waterways.

River height represents daily mean discharge, width uses each river’s monthly mean from the available observations, and colour represents daily mean water temperature. All three metrics (discharge, level, temperature) use BoM’s `DMQaQc.Merged.DailyMean.24HR` series; the viewer holds each day’s reading and leaves missing daily means blank. Values between gauges are estimates. Grey-blue reaches have no temperature observation. Combined gauge totals include upstream gauges and do not represent basin outflow.

## View the site

The viewer is a static site. `index.html` loads the prepared observations and river geometry from `data/data.js`; MapLibre, deck.gl, and fonts load from external services.

For a local preview:

```sh
python3 -m http.server 8765
```

Open http://localhost:8765/.

## GitHub Pages

In repository **Settings → Pages**, select **Deploy from a branch**, **main**, and **/ (root)**. The `.nojekyll` file keeps the site as plain static files.

## Refresh the data

Python scripts maintain a local SQLite observation store and export the browser data bundle. The database is excluded from Git.

```sh
python3 scripts/fetch_bom.py --daily-means --stations data/all_fetch.json --from 2026-10-01 --to 2026-10-21
python3 scripts/build_data.py --from 2026-10-01 --to 2026-10-21
```

Commit and push the regenerated `data/data.js` to update the published snapshot. GitHub Pages does not run the fetch scripts automatically. The viewer ends its timeline at the last interval with at least 90% of peak reporting coverage to avoid presenting incomplete final intervals as a sudden fall in discharge.

## Sources and credits

- Observations: [Bureau of Meteorology Water Data Online](https://www.bom.gov.au/waterdata/).
- Waterways: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the Open Database License.
- Visual and interaction inspiration: [mapped.earth](https://mapped.earth/river-pulse/).

To backfill the previous Australian water year (1 July 2025–30 June 2026), with checkpoints and retries:

```sh
python3 -I scripts/backfill_year.py --start-year 2025 --export-to 2026-10-21
```

The exporter combines that year with the current year. Completed request windows are stored in the local database so rerunning resumes unfinished requests. `data/backfill-2025-2026.json` records daily observation counts for every month; a completion timestamp is added only after all requests and the final export succeed. Valid empty responses remain gaps; failed requests stop the export after retries.
