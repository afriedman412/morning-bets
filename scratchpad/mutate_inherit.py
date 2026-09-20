"""Mutation-verify the inherited-runner checks.

Every wrong way of doing this measurement still produces a plausible ~0.33,
which is exactly why it needs mutation rather than eyeballing the output.

    venv/bin/python -m scratchpad.mutate_inherit
"""
import os
import pathlib
import shutil
import subprocess

SRC = pathlib.Path("src/context/inherit.py")
ORIGINAL = SRC.read_text()

MUTATIONS = [
    ("no half-inning flush — stranded runners never reach the denominator",
     "        if key != half:\n            flush()\n",
     "        if key != half:\n",
     "a_stranded_inherited_runner_counts_as_not_scoring"),

    ("any runner who scores counts, not just the inherited ones",
     '            if rid in pending and (end == "score" or is_out):',
     '            if (end == "score" or is_out) and pending:\n'
     '                rid = next(iter(pending))\n'
     '            if rid in pending and (end == "score" or is_out):',
     "the_relievers_own_baserunners_are_not_inherited"),

    ("inherited runners recorded as a COUNT, all keyed to first base",
     "                for base, rid in occupant.items():\n"
     "                    pending[rid] = (base, outs)",
     "                for base, rid in occupant.items():\n"
     "                    pending[rid] = (\"1B\", outs)",
     "every_runner_on_base_at_a_handover_is_recorded_on_his_own_base"),

    ("a runner re-inherited at a second change counted twice",
     "                for base, rid in occupant.items():\n"
     "                    pending[rid] = (base, outs)",
     "                for base, rid in occupant.items():\n"
     "                    if rid in pending:\n"
     "                        results.append((base, outs, False))\n"
     "                    pending[rid] = (base, outs)",
     "a_runner_inherited_twice_is_counted_once"),

    ("a runner thrown out on the bases counted as a run",
     '                results.append((base, at, end == "score"))',
     '                results.append((base, at, True))',
     "a_runner_thrown_out_on_the_bases_did_not_score"),

    ("place before vacate — the batter's record clears the scorer's base",
     "        for rid in order:\n"
     "            start = final[rid][0]\n"
     "            if start in _BASES and occupant.get(start) == rid:\n"
     "                del occupant[start]\n",
     "",
     "a_runner_who_advanced_is_inherited_on_his_CURRENT_base_only"),
]


def _bust_cache() -> None:
    for d in pathlib.Path(".").rglob("__pycache__"):
        if "venv" not in str(d):
            shutil.rmtree(d, ignore_errors=True)


def failures() -> set[str]:
    _bust_cache()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run(["venv/bin/python", "-m", "tests.run", "inherit"],
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
                print(f"          unguarded probe; failed: "
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
