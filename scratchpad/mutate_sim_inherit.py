"""Mutation-verify the inherited-runner wiring in sim.py.

    venv/bin/python -m scratchpad.mutate_sim_inherit
"""
import os
import pathlib
import shutil
import subprocess

SRC = pathlib.Path("src/context/sim.py")
ORIGINAL = SRC.read_text()

MUTATIONS = [
    ("per-base roll replaced by the pooled flat rate",
     "        scored = sum(1 for i, on in enumerate(fr.bases) if on\n"
     "                     and rng.random()"
     " < INHERITED_SCORE_BY_STATE[i][out_i])",
     "        scored = sum(1 for _ in range(r.left_on_base)\n"
     "                     if rng.random() < INHERITED_SCORE_RATE)",
     "inherited_runners_score_by_base_not_by_count"),

    ("flag ignored — measured path always taken",
     "    if USE_MEASURED_INHERITED:",
     "    if True:",
     "the_inherited_flag_off_restores_the_flat_rate"),

    ("outs ignored — every handover priced as nobody out",
     "        out_i = min(max(fr.outs, 0), 2)",
     "        out_i = 0",
     None),

    ("the measured table exposed to the fitter",
     '            "INHERITED_SCORE_RATE", "WP_PB_RATE", "GIDP_RATE",',
     '            "INHERITED_SCORE_RATE", "INHERITED_SCORE_BY_STATE",'
     ' "WP_PB_RATE", "GIDP_RATE",',
     "the_measured_inherited_table_is_not_fittable"),
]


def _bust_cache() -> None:
    for d in pathlib.Path(".").rglob("__pycache__"):
        if "venv" not in str(d):
            shutil.rmtree(d, ignore_errors=True)


def failures() -> set[str]:
    _bust_cache()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run(["venv/bin/python", "-m", "tests.run", "sim"],
                       capture_output=True, text=True, env=env)
    return {ln.split("FAIL  ")[1].split(":")[0].strip()
            for ln in p.stdout.splitlines() if "FAIL  " in ln}


def main() -> int:
    bad = 0
    try:
        for label, old, new, want in MUTATIONS:
            if old not in ORIGINAL:
                print(f"  SKIP  text not found: {label}")
                bad += 1
                continue
            SRC.write_text(ORIGINAL.replace(old, new, 1))
            got = failures()
            if want is None:
                print(f"  --    {label}")
                print(f"          probe; failed: "
                      f"{', '.join(sorted(got)) or '(nothing)'}")
                continue
            ok = want in got
            print(f"  {'ok  ' if ok else 'MISS'}  {label}")
            print(f"          expected {want}")
            print(f"          failed:  {', '.join(sorted(got)) or '(nothing)'}")
            if not ok:
                bad += 1
    finally:
        SRC.write_text(ORIGINAL)
    print(f"\n{bad} misses")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
