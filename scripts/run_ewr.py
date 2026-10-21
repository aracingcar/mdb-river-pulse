#!/usr/bin/env python3
"""Assess MDBA environmental watering requirements (py_ewr) against the daily series in data/data.js.

Writes data/ewr-events.js: for every EWR and water year that py_ewr counts as achieved (its `<code>_eventYears` flag), the
spells that achieved it and the day it was achieved, plus spells beyond each EWR's maximum inter-event period. Also stores
ewr_achievements and ewr_summary in the SQLite store. Run with an interpreter that has py_ewr, pandas and numpy installed.
"""
import argparse, json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
from py_ewr import data_inputs, evaluate_EWRs
from py_ewr.scenario_handling import ScenarioHandler

ROOT = Path(__file__).resolve().parents[1]
warnings.filterwarnings("ignore")


def load():
    s = (ROOT / "data/data.js").read_text()
    return json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))


def store(db, rows, summary):
    """Replace the ewr_achievements / ewr_summary tables in the SQLite observation store (all gauges re-assessed each run)."""
    import sqlite3
    ach = pd.DataFrame(rows, columns=["gauge", "planning_unit", "ewr", "water_year", "start_date", "end_date", "achieved_on", "spells"])
    sm = summary.drop(columns=["Scenario"]).rename(columns={c: c.lower() for c in summary.columns})
    sm["gauge"] = sm["gauge"].astype(str)
    with sqlite3.connect(db) as con:
        con.execute("DROP TABLE IF EXISTS ewr_events")   # earlier versions stored every spell meeting the minimum length, which over-counts achievement
        ach.to_sql("ewr_achievements", con, if_exists="replace", index=False)
        sm.to_sql("ewr_summary", con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS ewr_ach_gauge ON ewr_achievements(gauge, start_date)")
    print(f"stored {len(ach)} achieved EWR-years, {len(sm)} summary rows in {db}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/river.db"))
    ap.add_argument("--out", default=str(ROOT / "data/ewr-events.js"))
    ap.add_argument("--gauges", nargs="*")
    a = ap.parse_args()
    a_db = a.db

    j = load()
    n = j["meta"]["n"]
    idx = pd.date_range(j["meta"]["start"][:10], periods=n, freq="D")
    table = data_inputs.get_EWR_table()
    ewr_gauges = set(table["Gauge"].astype(str))
    by_id = {g["id"]: g for g in j["gauges"]}
    ids = [i for i in by_id if i in ewr_gauges and (not a.gauges or i in a.gauges)]

    def frame(key):
        cols = {i: pd.Series(by_id[i][key], index=idx, dtype="float64") for i in ids if by_id[i].get(key)}
        df = pd.DataFrame(cols, index=idx)
        df.index.name = "Date"
        return df

    df_F, df_L = frame("flow"), frame("level")
    calc_config = data_inputs.get_ewr_calc_config(None)
    results, events, errors = {}, {}, {}
    for gid in sorted(set(df_F.columns) | set(df_L.columns)):
        try:
            results[gid], events[gid] = evaluate_EWRs.calc_sorter(df_F, df_L, gid, table, calc_config)
        except Exception as e:
            errors[gid] = f"{type(e).__name__}: {e}"
        print(gid, "ok" if gid in results else errors[gid], file=sys.stderr)

    sh = ScenarioHandler("scenario.csv", "Standard time-series")
    sh.pu_ewr_statistics, sh.yearly_events, sh.flow_data, sh.level_data = {"s": results}, {"s": events}, df_F, df_L
    summary = sh.get_ewr_results()

    # ecological objective groups each EWR serves (py_ewr objective mapping, by objective target)
    group = {"Native Fish": "NF", "Waterbirds": "WB", "Native Vegetation": "NV", "Ecosystem Functions": "EF", "Other Species": "OS"}
    objm = data_inputs.get_obj_mapping()
    obj, obj_codes = {}, {}
    for g, pu, c, t, eco in zip(objm.Gauge.astype(str), objm.PlanningUnitName, objm.Code, objm.Target, objm.EcoObj):
        if t in group:
            obj.setdefault((g, pu, c), set()).add(group[t])
            obj_codes.setdefault((g, pu, c), set()).add((group[t], str(eco)))
    def mrip_days(y):
        y = pd.to_numeric(y, errors="coerce")
        return 0 if pd.isna(y) or y <= 0 else int(round(float(y) * 365.25))

    # one definition per assessed EWR: [gauge, code, planning unit, target frequency (% of years), objective groups, SDL unit, max inter-event days (0 = none), [theme, ecological objective code] pairs]
    defs, def_ix = [], {}
    for r in summary.itertuples():
        key = (str(r.Gauge), r.PlanningUnit, r.Code)
        tf = pd.to_numeric(r.TargetFrequency, errors="coerce")
        if key in def_ix:
            continue
        tf = 0.0 if pd.isna(tf) else tf   # EWRs without a target frequency are kept (they still pop) but are not scored
        def_ix[key] = len(defs)
        defs.append([key[0], key[2], key[1], float(tf), sorted(obj.get(key, [])), str(r.SWSDLName), mrip_days(r.MaxInterEventYears), sorted(list(x) for x in obj_codes.get(key, []))])
    pos = {d: i for i, d in enumerate(idx)}
    par = {(str(g), pu, c): (d, ms, epy) for g, pu, c, d, ms, epy in zip(
        table.Gauge, table.PlanningUnitName, table.Code,
        pd.to_numeric(table.Duration, errors="coerce").fillna(1), pd.to_numeric(table.MinSpell, errors="coerce").fillna(1), pd.to_numeric(table.EventsPerYear, errors="coerce").fillna(1))}

    def day(x):
        x = x[0] if isinstance(x, tuple) else x
        return pos.get(pd.Timestamp(x).normalize())

    # An EWR is achieved in a water year when py_ewr sets its <code>_eventYears flag. The spells that achieved it are the first EventsPerYear
    # spells lasting at least the required duration; it is achieved on the day the last of them reaches that duration.
    ev, rows = {}, []
    for gid, res in results.items():
        for pu, r in res.items():
            for col in [c for c in r if c.endswith("_eventYears")]:
                code = col[:-len("_eventYears")]
                di = def_ix.get((gid, pu, code), -1)
                if di < 0:
                    continue
                dur, minspell, epy = par.get((gid, pu, code), (1, 1, 1))
                dur, need = max(int(dur), int(minspell), 1), max(int(epy), 1)
                by_year = events.get(gid, {}).get(pu, {}).get(code, {})
                for y, flag in r[col].items():
                    if flag != 1:
                        continue
                    try:
                        spells = [(day(sp[0]), day(sp[-1])) for sp in by_year.get(y, []) if len(sp)]
                    except Exception:
                        continue
                    spells = sorted((s_, e_) for s_, e_ in spells if s_ is not None and e_ is not None)
                    good = [x for x in spells if x[1] - x[0] + 1 >= dur] or sorted(spells, key=lambda x: x[0] - x[1])[:need]   # fall back to the longest spells
                    chosen = good[:need]
                    if not chosen:
                        continue
                    last = chosen[-1]
                    ok = min(last[0] + dur - 1, last[1])
                    ev.setdefault(gid, []).append([code, chosen[0][0], last[1], ok, di, [list(x) for x in chosen]])
                    rows.append([gid, pu, code, int(y), idx[chosen[0][0]].strftime("%Y-%m-%d"), idx[last[1]].strftime("%Y-%m-%d"), idx[ok].strftime("%Y-%m-%d"), len(chosen)])
    for v in ev.values():
        v.sort(key=lambda x: (x[1], x[0]))
    store(a_db, rows, summary)

    # spells beyond the maximum inter-event period: [def, first day over, last day over, ended by an event (1) or still running (0)]
    first_day = {}
    for gid in set(df_F.columns) | set(df_L.columns):
        firsts = [pos[x.first_valid_index()] for x in (df_F.get(gid), df_L.get(gid)) if x is not None and x.first_valid_index() is not None]
        first_day[gid] = min(firsts) if firsts else None
    spans = {}
    for gid, rows in ev.items():
        for code, st, en, ok, di, _ in rows:
            if di >= 0:
                spans.setdefault(di, []).append((st, en))
    gaps = []
    for di, (gid, code, pu, tf, cats, sdl, mrip, _objs) in enumerate(defs):  # the trailing objectives field is unused here
        if mrip <= 0 or first_day.get(gid) is None:
            continue
        prev_end = first_day[gid] - 1
        segs = sorted(spans.get(di, []))
        for st, en in segs + [(None, None)]:
            nxt = st if st is not None else n
            lo, hi = prev_end + 1 + mrip, nxt - 1
            if lo <= hi:
                gaps.append([di, lo, hi, 0 if st is None else 1])
            if en is not None:
                prev_end = max(prev_end, en)

    stats = {}
    for r in summary.itertuples():
        stats.setdefault(str(r.Gauge), []).append([
            r.Code, r.PlanningUnit,
            None if pd.isna(r.EventYears) else int(r.EventYears),
            None if pd.isna(r.Frequency) else round(float(r.Frequency), 1),
            None if pd.isna(r.TargetFrequency) else float(r.TargetFrequency),
        ])
    out = {"gauges": len(results), "errors": errors, "objectives": {"NF": "Native fish", "WB": "Waterbirds", "NV": "Native vegetation", "EF": "Ecosystem functions", "OS": "Other species"}, "defs": defs, "events": ev, "gaps": gaps, "stats": stats}
    Path(a.out).write_text("window.EWR_EVENTS=" + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"{len(results)} gauges, {sum(map(len, ev.values()))} achieved EWR-years, {len(errors)} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
