"""Mutation-verify the relief checks.

A check that guards nothing looks identical to one that guards something,
and this project has shipped three of the former. Each mutation below
reintroduces a specific bug; the named check MUST fail, and ideally only it.

    venv/bin/python -m scratchpad.mutate_relief
"""
import os
import pathlib
import shutil
import subprocess

SRC = pathlib.Path("src/context/relief.py")
ORIGINAL = SRC.read_text()

#: (label, old, new, the check that must catch it)
MUTATIONS = [
    ("pooled entry table — one constant for every entry state",
     "CONTINUE_AFTER_ENTRY_INNING = {0: 0.2013, 1: 0.4478, 2: 0.6267}",
     "CONTINUE_AFTER_ENTRY_INNING = {0: 0.30, 1: 0.30, 2: 0.30}",
     "continuation_rises_with_the_out_count_at_entry"),

    ("entry table indexed forever — a two-out entry never leaves",
     "    if extra_innings <= 0:\n",
     "    if True:\n",
     "extra_innings_use_the_extra_table_not_the_entry_table"),

    ("no tail fallback past the measured span",
     "    return CONTINUE_AFTER_EXTRA.get(extra_innings, CONTINUE_TAIL)",
     "    return CONTINUE_AFTER_EXTRA[extra_innings]",
     "a_long_outing_falls_back_to_the_tail_rate"),

    ("entry_outs unclamped",
     "        return CONTINUE_AFTER_ENTRY_INNING.get(min(max(entry_outs, 0), 2),\n"
     "                                               CONTINUE_AFTER_ENTRY_INNING[0])",
     "        return CONTINUE_AFTER_ENTRY_INNING[entry_outs]",
     "an_out_of_range_entry_count_does_not_raise"),

    ("continuation counted by OUTS RECORDED instead of innings spanned",
     '        c = sum(1 for r in g if r["last_inning"] > r["entry_inning"])',
     '        c = sum(1 for r in g if r["outs_recorded"] > 3)',
     "tally_counts_a_continuation_by_the_innings_spanned"),

    ("mid-inning counted by entry_outs only, ignoring inherited runners",
     '        if r["entry_outs"] > 0 or r["on_1b"] or r["on_2b"] or r["on_3b"]',
     '        if r["entry_outs"] > 0',
     "mid_inning_entry_counts_runners_as_well_as_outs"),

    ("removal hazard flattened to one pooled constant",
     "RELIEF_MID_REMOVAL = {\n"
     "    0: {0: 0.015, 1: 0.099, 2: 0.073, 3: 0.070},",
     "RELIEF_MID_REMOVAL = {\n"
     "    0: {0: 0.047, 1: 0.047, 2: 0.047, 3: 0.047},",
     "a_just_arrived_reliever_is_nearly_immune"),

    ("removal hazard made monotone in batters faced",
     "    0: {0: 0.015, 1: 0.099, 2: 0.073, 3: 0.070},",
     "    0: {0: 0.015, 1: 0.040, 2: 0.070, 3: 0.099},",
     "the_removal_hazard_is_not_monotone_in_batters_faced"),

    ("removal inputs unclamped",
     "    r = RELIEF_MID_REMOVAL[min(max(runs, 0), 3)]\n"
     "    return r[min(max(batters, 0) // 3, 3)]",
     "    return RELIEF_MID_REMOVAL[runs][batters // 3]",
     "removal_inputs_are_clamped"),
]


def _bust_cache() -> None:
    """A mutation that preserves file SIZE is invisible to Python's cache.

    `.pyc` validity is (mtime, size), and this harness rewrites the source
    twice inside the same mtime second — so `+= 1` -> `+= 0` reuses stale
    bytecode and the mutation silently does not happen. That reports a real
    check as unguarded. Clear the caches and refuse to write new ones.
    """
    for d in pathlib.Path(".").rglob("__pycache__"):
        if "venv" not in str(d):
            shutil.rmtree(d, ignore_errors=True)


def failures() -> set[str]:
    _bust_cache()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run(["venv/bin/python", "-m", "tests.run", "relief"],
                       capture_output=True, text=True, env=env)
    return {ln.split("FAIL  ")[1].split(":")[0].strip()
            for ln in p.stdout.splitlines() if "FAIL  " in ln}


def main() -> int:
    bad = 0
    try:
        for label, old, new, want in MUTATIONS:
            if old not in ORIGINAL:
                print(f"  SKIP  mutation text not found: {label}")
                bad += 1
                continue
            SRC.write_text(ORIGINAL.replace(old, new, 1))
            got = failures()
            ok = want in got
            extra = got - {want}
            print(f"  {'ok  ' if ok else 'MISS'}  {label}")
            print(f"          expected {want}")
            print(f"          failed:  {', '.join(sorted(got)) or '(nothing)'}")
            if extra:
                print(f"          also caught: {', '.join(sorted(extra))}")
            if not ok:
                bad += 1
    finally:
        SRC.write_text(ORIGINAL)
    print(f"\n{len(MUTATIONS) - bad}/{len(MUTATIONS)} mutations caught")
    print("restored", SRC)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
