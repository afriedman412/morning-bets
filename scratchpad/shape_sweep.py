"""Collapse a `shape.py` sigma sweep into one table.

    venv/bin/python -m scratchpad.shape_sweep scratchpad/shape_s*.out

Reads the files `shape.py` wrote, one per sigma, and prints the handful of
numbers the decision actually turns on. The pre-registered predictions are
listed alongside so a reader can check them against the columns rather than
against a memory of what was expected.

WHAT WOULD FALSIFY THE MECHANISM, stated before the sweep ran: the term is
supposed to reproduce SELECTION — sharp nights are long AND high-K — not to
add spread. So sd(K) must widen in the LONG buckets, where the model is
short, and NOT in the short ones (0-8, 9-11, 12-14), where it already
matches within a standard error. Uniform widening is dispersion bought for
nothing, which is the failure mode the early-exit mixture and the
`early_innings` branches were both rejected for.
"""
from __future__ import annotations

import re
import sys


def parse(path):
    txt = open(path).read()
    d = {"file": path}
    m = re.search(r"sigma ([\d.]+)", txt)
    d["sigma"] = float(m.group(1)) if m else None
    for label, key in (("OUTS", "outs"), ("K", "k")):
        blk = re.search(rf"=== {label} .*?===(.*?)(?====|\Z)", txt, re.S)
        if not blk:
            continue
        b = blk.group(1)
        for field, pat in (("mean", r"mean\s+([\d.]+)\s+([\d.]+)"),
                           ("sd", r"\n\s+sd\s+([\d.]+)\s+([\d.]+)"),
                           ("bnd", r"boundary share\s+([\d.]+)\s+([\d.]+)")):
            mm = re.search(pat, b)
            if mm:
                d[f"{key}_{field}"] = float(mm.group(1))
                d[f"{key}_{field}_act"] = float(mm.group(2))
        mm = re.search(r"CRPS\s+([\d.]+)", b)
        if mm:
            d[f"{key}_crps"] = float(mm.group(1))
        for ln in ("8.5", "9.5"):
            mm = re.search(rf"o{ln}\s+([\d.]+)\s+([\d.]+)", b)
            if mm:
                d[f"{key}_o{ln}"] = float(mm.group(1))
                d[f"{key}_o{ln}_act"] = float(mm.group(2))
    for lo, hi in (("0", "8"), ("9", "11"), ("12", "14"),
                   ("15", "17"), ("18", "20"), ("21", "27")):
        mm = re.search(rf"\n\s+{lo}-{hi}\s+\d+\s+([\d.]+)\s+([\d.]+)"
                       rf"\s+([\d.]+)\s+([\d.]+)\s+([+-][\d.]+)", txt)
        if mm:
            d[f"ek_{lo}"] = float(mm.group(1))
            d[f"ek_{lo}_act"] = float(mm.group(2))
            d[f"sdk_{lo}"] = float(mm.group(3))
            d[f"sdk_{lo}_act"] = float(mm.group(4))
    return d


def main(paths):
    rows = sorted((parse(p) for p in paths), key=lambda r: r["sigma"])
    a = rows[0]
    print("\n  === THE TARGET: what the shipped engine gets wrong ===")
    print(f"    K sd            {a['k_sd']:.2f} against {a['k_sd_act']:.2f}")
    print(f"    K o8.5          {a['k_o8.5']:.3f} against {a['k_o8.5_act']:.3f}")
    print(f"    E[K|21-27]      {a.get('ek_21', 0):.2f} against "
          f"{a.get('ek_21_act', 0):.2f}")
    print(f"    outs boundary   {a['outs_bnd']:.3f} against "
          f"{a['outs_bnd_act']:.3f}")

    print("\n  === SWEEP ===")
    print(f"    {'sigma':>6}{'K sd':>7}{'K CRPS':>9}{'o8.5':>7}{'o9.5':>7}"
          f"{'E[K|21+]':>10}{'outs mn':>9}{'outs sd':>9}{'bnd':>7}"
          f"{'o CRPS':>9}")
    print(f"    {'ACTUAL':>6}{a['k_sd_act']:>7.2f}{'':>9}"
          f"{a['k_o8.5_act']:>7.3f}{a['k_o9.5_act']:>7.3f}"
          f"{a.get('ek_21_act', 0):>10.2f}{a['outs_mean_act']:>9.2f}"
          f"{a['outs_sd_act']:>9.2f}{a['outs_bnd_act']:>7.3f}{'':>9}")
    for r in rows:
        print(f"    {r['sigma']:>6.2f}{r['k_sd']:>7.2f}{r['k_crps']:>9.4f}"
              f"{r['k_o8.5']:>7.3f}{r['k_o9.5']:>7.3f}"
              f"{r.get('ek_21', 0):>10.2f}{r['outs_mean']:>9.2f}"
              f"{r['outs_sd']:>9.2f}{r['outs_bnd']:>7.3f}"
              f"{r['outs_crps']:>9.4f}")

    print("\n  === THE FALSIFIER: sd(K|outs) gap by bucket ===")
    print("    widening must land in the LONG buckets only; uniform")
    print("    widening is spread bought for nothing and fails this.")
    print(f"    {'sigma':>6}" + "".join(f"{b:>10}" for b in
          ("0-8", "9-11", "12-14", "15-17", "18-20", "21-27")))
    for r in rows:
        cells = ""
        for lo in ("0", "9", "12", "15", "18", "21"):
            g = r.get(f"sdk_{lo}")
            cells += (f"{g - r[f'sdk_{lo}_act']:>+10.2f}"
                      if g is not None else f"{'-':>10}")
        print(f"    {r['sigma']:>6.2f}{cells}")


if __name__ == "__main__":
    main(sys.argv[1:])
