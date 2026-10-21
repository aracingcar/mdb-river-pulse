#!/bin/sh
# Backfill months newest-first for the water year (from 1 July).
cd "$(dirname "$0")/.." || exit 1
for r in "2026-09-01 2026-09-30" "2026-08-01 2026-08-31" "2026-07-01 2026-07-31"; do
  set -- $r; echo "== $1 .. $2"
  python3 -I scripts/fetch_bom.py --stations data/all_fetch.json --backfill --from $1 --to $2 || exit 1
  python3 -I scripts/build_data.py --from 2026-$(echo $1 | cut -d- -f2)-01 --to 2026-10-21 || exit 1
done
