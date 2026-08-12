"""Scan CH SAVs for child-age source columns (metadata-only; fast).

For each dataset report presence of:
  CAGE (direct age in completed months),
  MICS4/5 date parts: interview UF8M/UF8Y, birth AG1M/AG1Y,
  MICS6   date parts: interview UF7M/UF7Y, birth UB1M/UB1Y.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pyreadstat

RAW = Path("/Volumes/MikesDataBackup/MICS/raw")
OUT = Path(__file__).parent.parent / "scratch_child_age_scan.json"

CAGE = ["CAGE", "cage", "Cage"]
SETS = {
    "m45": (["UF8M"], ["UF8Y"], ["AG1M"], ["AG1Y"]),   # MICS4/5 interview / birth
    "m6":  (["UF7M"], ["UF7Y"], ["UB1M"], ["UB1Y"]),   # MICS6 interview / birth
}


def _ch_sav(ds):
    d = RAW / ds
    if not d.is_dir():
        return None
    for pat in ("ch.sav", "CH.sav", "Ch.sav"):
        if (d / pat).exists():
            return d / pat
    cands = [p for p in d.glob("*.sav") if "ch" in p.name.lower()]
    return cands[0] if cands else None


def _has(cols_low, names):
    return next((n for n in names if n.lower() in cols_low), None)


def main():
    import psycopg2
    c = psycopg2.connect(host="localhost", port=5432, dbname="mda", user="lichao")
    cur = c.cursor()
    cur.execute('SELECT DISTINCT dataset_name FROM "final_CH_MICS" ORDER BY 1')
    datasets = [r[0] for r in cur.fetchall()]
    c.close()
    rows = []
    for i, ds in enumerate(datasets):
        sav = _ch_sav(ds)
        if sav is None:
            rows.append({"ds": ds, "sav": None}); continue
        try:
            _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
        except Exception as e:
            rows.append({"ds": ds, "sav": str(sav), "err": str(e)[:80]}); continue
        low = {c.lower(): c for c in meta.column_names}
        rec = {"ds": ds, "sav": sav.name,
               "cage": _has(low, CAGE)}
        for k, (im, iy, bm, by) in SETS.items():
            rec[k] = {"im": _has(low, im), "iy": _has(low, iy),
                      "bm": _has(low, bm), "by": _has(low, by)}
        rows.append(rec)
        if (i + 1) % 25 == 0:
            print(f"  scanned {i+1}/{len(datasets)}", flush=True)
    OUT.write_text(json.dumps(rows, indent=0))
    # summary
    n_cage = sum(1 for r in rows if r.get("cage"))
    n45 = sum(1 for r in rows if r.get("m45") and all(r["m45"].values()))
    n6 = sum(1 for r in rows if r.get("m6") and all(r["m6"].values()))
    n_date_any = sum(1 for r in rows if (r.get("m45") and all(r["m45"].values())) or (r.get("m6") and all(r["m6"].values())))
    nosav = sum(1 for r in rows if r.get("sav") is None)
    print(f"\nTOTAL datasets={len(rows)}  no-SAV={nosav}")
    print(f"  CAGE present:            {n_cage}")
    print(f"  full MICS4/5 date parts: {n45}")
    print(f"  full MICS6   date parts: {n6}")
    print(f"  any full date set:       {n_date_any}")
    print(f"  CAGE or date:            {sum(1 for r in rows if r.get('cage') or (r.get('m45') and all(r['m45'].values())) or (r.get('m6') and all(r['m6'].values())))}")
    print(f"written -> {OUT}")


if __name__ == "__main__":
    main()
