"""Mutation-verify the three new game.py wiring checks.

Same contract as `mutate_relief`: each mutation reintroduces the exact bug
the check claims to guard, and the named check must fail.

    venv/bin/python -m scratchpad.mutate_game
"""
import os
import pathlib
import shutil
import subprocess

SRC = pathlib.Path("src/context/game.py")
ORIGINAL = SRC.read_text()

MUTATIONS = [
    ("give way unconditionally — the pre-measurement engine",
     "        if USE_MEASURED_RELIEF_LENGTH:\n"
     "            p = relief.continues(side.cur_entry_outs,"
     " side.cur_extra_innings)\n"
     "            if rng.random() < p:\n"
     "                side.cur_extra_innings += 1\n"
     "                return\n",
     "",
     "a_reliever_can_work_more_than_one_inning"),

    ("flag ignored — measured length always on",
     "        if USE_MEASURED_RELIEF_LENGTH:",
     "        if True:",
     "relief_length_flag_off_restores_one_inning_each"),

    ("mid-inning handover drops the out count",
     # Anchor on the STARTER's call. Since the relief hook landed there are
     # two `next_arm(fr.outs)` sites and the relief one comes first, so a
     # bare replace(...,1) silently mutates the wrong branch.
     "                # and comes back out 63% of the time.\n"
     "                side.next_arm(fr.outs)",
     "                # and comes back out 63% of the time.\n"
     "                side.next_arm()",
     "a_mid_inning_hook_hands_over_the_out_count"),

    ("extra innings never accumulate — the hazard resets every inning",
     "                side.cur_extra_innings += 1",
     "                side.cur_extra_innings += 0",
     "the_continuation_hazard_advances_with_each_extra_inning"),

    ("relievers can never be pulled mid-inning (pre-measurement engine)",
     "        if side.starter_out and USE_MEASURED_RELIEF_HOOK:\n"
     "            rl = side.cur_line\n"
     "            if rng.random() < relief.mid_removal(rl.runs, rl.batters):\n"
     "                side.next_arm(fr.outs)\n"
     "        elif not side.starter_out:",
     "        if not side.starter_out:",
     "a_reliever_can_be_pulled_mid_inning"),

    ("relief hook flag ignored",
     "        if side.starter_out and USE_MEASURED_RELIEF_HOOK:",
     "        if side.starter_out:",
     "the_relief_hook_flag_off_leaves_relievers_alone"),
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
    p = subprocess.run(["venv/bin/python", "-m", "tests.run", "game"],
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
            if want is None:
                print(f"  --    {label}")
                print(f"          NOT GUARDED by design; failed: "
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
    print("restored", SRC)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
