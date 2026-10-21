# Murray–Darling River Pulse

An interactive river map inspired by [mapped.earth’s River Pulse](https://mapped.earth/river-pulse/), using Bureau of Meteorology Water Data Online observations and OpenStreetMap waterways.

River height represents discharge, width uses the mean over the available observations, and colour represents water temperature. Values between gauges are estimates. Grey-blue reaches have no temperature observation. Combined gauge totals include upstream gauges and do not represent basin outflow.

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
python3 scripts/fetch_bom.py --stations data/all_fetch.json --from 2026-10-01 --to 2026-10-21
python3 scripts/build_data.py --from 2026-10-01 --to 2026-10-21
```

Commit and push the regenerated `data/data.js` to update the published snapshot. GitHub Pages does not run the fetch scripts automatically. The viewer ends its timeline at the last interval with at least 90% of peak reporting coverage to avoid presenting incomplete final intervals as a sudden fall in discharge.

## Sources and credits

- Observations: [Bureau of Meteorology Water Data Online](https://www.bom.gov.au/waterdata/).
- Waterways: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the Open Database License.
- Visual and interaction inspiration: [mapped.earth](https://mapped.earth/river-pulse/).
