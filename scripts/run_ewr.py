#!/usr/bin/env python3
"""Assess MDBA environmental watering requirements (py_ewr) against the daily series in data/data.js.

Writes data/ewr-events.js: every successful EWR event (gauge, code, start/end day index) and a per-EWR
summary. Run with an interpreter that has py_ewr, pandas and numpy installed.
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


def store(db, succ, summary, min_dur):
    """Replace the ewr_events / ewr_summary tables in the SQLite observation store (all gauges re-assessed each run)."""
    import sqlite3
    ev = pd.DataFrame({
        "gauge": succ.Gauge.astype(str), "planning_unit": succ.PlanningUnit, "ewr": succ.Code,
        "water_year": pd.to_numeric(succ.waterYear, errors="coerce"),
        "start_date": pd.to_datetime(succ.startDate).dt.strftime("%Y-%m-%d"),
        "end_date": pd.to_datetime(succ.endDate).dt.strftime("%Y-%m-%d"),
        "event_length": pd.to_numeric(succ.eventLength, errors="coerce"),
        "min_duration": [min_dur.get((str(g), pu, c)) for g, pu, c in zip(succ.Gauge, succ.PlanningUnit, succ.Code)],
        "state": succ.State, "sdl": succ.SWSDLName,
    })
    sm = summary.drop(columns=["Scenario"]).rename(columns={c: c.lower() for c in summary.columns})
    sm["gauge"] = sm["gauge"].astype(str)
    with sqlite3.connect(db) as con:
        ev.to_sql("ewr_events", con, if_exists="replace", index=False)
        sm.to_sql("ewr_summary", con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS ewr_events_gauge ON ewr_events(gauge, start_date)")
    print(f"stored {len(ev)} events, {len(sm)} summary rows in {db}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/river.db"))
    ap.add_argument("--out", default=str(ROOT / "data/ewr-events.js"))
    ap.add_argument("--gauges", nargs="*")
    a = ap.parse_args()

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
    succ = sh.get_all_successful_events()

    min_dur = {(str(g), pu, c): d for g, pu, c, d in zip(table.Gauge, table.PlanningUnitName, table.Code, pd.to_numeric(table.Duration, errors="coerce").fillna(1))}
    store(a.db, succ, summary, min_dur)
    # ecological objective groups each EWR serves (py_ewr objective mapping, by objective target)
    group = {"Native Fish": "NF", "Waterbirds": "WB", "Native Vegetation": "NV", "Ecosystem Functions": "EF", "Other Species": "OS"}
    objm = data_inputs.get_obj_mapping()
    obj = {}
    for g, pu, c, t in zip(objm.Gauge.astype(str), objm.PlanningUnitName, objm.Code, objm.Target):
        if t in group:
            obj.setdefault((g, pu, c), set()).add(group[t])
    def mrip_days(y):
        y = pd.to_numeric(y, errors="coerce")
        return 0 if pd.isna(y) or y <= 0 else int(round(float(y) * 365.25))

    # one definition per assessed EWR: [gauge, code, planning unit, target frequency (% of years), objective groups, SDL unit, max inter-event days (0 = none)]
    defs, def_ix = [], {}
    for r in summary.itertuples():
        key = (str(r.Gauge), r.PlanningUnit, r.Code)
        tf = pd.to_numeric(r.TargetFrequency, errors="coerce")
        if key in def_ix or pd.isna(tf) or tf <= 0:
            continue
        def_ix[key] = len(defs)
        defs.append([key[0], key[2], key[1], float(tf), sorted(obj.get(key, [])), str(r.SWSDLName), mrip_days(r.MaxInterEventYears)])
    pos = {d: i for i, d in enumerate(idx)}
    ev = {}
    for r in succ.itertuples():
        s, e = pd.Timestamp(r.startDate).normalize(), pd.Timestamp(r.endDate).normalize()
        if s not in pos or e not in pos:
            continue
        # day the event qualified: start + minimum duration (py_ewr events run to the end of the flow spell)
        dur = min_dur.get((str(r.Gauge), r.PlanningUnit, r.Code), 1)
        ok = min(pos[s] + max(int(dur), 1) - 1, pos[e])
        di = def_ix.get((str(r.Gauge), r.PlanningUnit, r.Code), -1)
        ev.setdefault(str(r.Gauge), []).append([r.Code, pos[s], pos[e], ok, di])
    for v in ev.values():
        v.sort(key=lambda x: (x[1], x[0]))

    # spells beyond the maximum inter-event period: [def, first day over, last day over, ended by an event (1) or still running (0)]
    first_day = {}
    for gid in set(df_F.columns) | set(df_L.columns):
        firsts = [pos[x.first_valid_index()] for x in (df_F.get(gid), df_L.get(gid)) if x is not None and x.first_valid_index() is not None]
        first_day[gid] = min(firsts) if firsts else None
    spans = {}
    for gid, rows in ev.items():
        for code, st, en, ok, di in rows:
            if di >= 0:
                spans.setdefault(di, []).append((st, en))
    gaps = []
    for di, (gid, code, pu, tf, cats, sdl, mrip) in enumerate(defs):
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
    print(f"{len(results)} gauges, {sum(map(len, ev.values()))} successful events, {len(errors)} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
