"""Mutation sweep: which checks actually bite?

A check that guards nothing looks identical to one that guards something.
Two were found by accident today — one converting batters to strikeouts at
the league rate when the marginal batter is a late-pass batter, one asserting
a 2% threshold on a measurement whose standard error is 5%. Both had been
passing for months without testing anything.

The only honest way to find the rest is to break the code on purpose and see
what fails. Each mutation flips one constant or drops one term; a mutation
that kills NOTHING means that line is unguarded, and a check that survives
every mutation touching its subject is a candidate for deletion.

Writes scratchpad/mutation_report.txt. Slow by design — the suite is ~60s
and there are dozens of mutations — so run it in the background.

    venv/bin/python -m scratchpad.mutate
"""
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "scratchpad" / "mutation_report.txt"

#: (file, pattern, replacement, label). Each must be a real behaviour change.
MUTATIONS = [
    ("src/context/sim.py", r"^ROE_PER_OUT = [\d.]+", "ROE_PER_OUT = 0.0",
     "errors never happen"),
    ("src/context/sim.py", r"^USE_TTO = True", "USE_TTO = False",
     "times through the order does nothing"),
    ("src/context/sim.py", r"^USE_MEASURED_ADVANCEMENT = True",
     "USE_MEASURED_ADVANCEMENT = False", "advancement reverts to imported"),
    ("src/context/sim.py", r"^USE_MEASURED_INHERITED = True",
     "USE_MEASURED_INHERITED = False", "inherited runners revert to flat"),
    ("src/context/sim.py", r"    late_mid_per_pitch: float = [\d.]+",
     "    late_mid_per_pitch: float = 0.0", "late hook ignores pitch count"),
    ("src/context/sim.py", r"    late_mid_per_onbase: float = [\d.]+",
     "    late_mid_per_onbase: float = 0.0", "late hook ignores bases occupied"),
    ("src/context/sim.py", r"    late_mid_per_inning_br: float = [\d.]+",
     "    late_mid_per_inning_br: float = 0.0",
     "late hook ignores traffic allowed"),
    ("src/context/sim.py", r"    per_baserunner: float = [\d.]+",
     "    per_baserunner: float = 0.0", "boundary hook ignores baserunners"),
    ("src/context/sim.py", r"    per_inning: float = [\d.]+",
     "    per_inning: float = 0.0", "boundary hook ignores the inning"),
    ("src/context/sim.py", r"    per_run: float = [\d.]+",
     "    per_run: float = 0.0", "boundary hook ignores runs"),
    ("src/context/sim.py", r"    hard_pitch_cap: int = \d+",
     "    hard_pitch_cap: int = 100000", "no hard pitch cap"),
    ("src/context/sim.py", r"^MID_INNING_RUN_OFFSET = \{[^}]*\}",
     "MID_INNING_RUN_OFFSET = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}",
     "current-inning runs offset flattened"),
    ("src/context/game.py", r"^USE_MEASURED_RELIEF_LENGTH = True",
     "USE_MEASURED_RELIEF_LENGTH = False", "relief outings are one inning"),
    ("src/context/game.py", r"^USE_MEASURED_RELIEF_HOOK = True",
     "USE_MEASURED_RELIEF_HOOK = False", "relievers are never pulled mid-inning"),
    ("src/context/game.py", r"^USE_LEARNED_HOOK = False",
     "USE_LEARNED_HOOK = True", "learned hook switched back on"),
    ("src/context/sim.py", r"    early_innings: int = \d+",
     "    early_innings: int = 3", "early branches switched on"),
]


def run_suite():
    t = time.time()
    p = subprocess.run([str(ROOT / "venv/bin/python"), "-m", "tests.run"],
                       cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    fails = re.findall(r"^  FAIL  (\S+?):", p.stdout, re.M)
    return fails, time.time() - t


def _guard():
    """Refuse to run against a dirty tree, and restore on ANY exit.

    THIS HARNESS CORRUPTED THE SOURCE ONCE. A two-minute timeout SIGKILLed
    it between mutating and restoring, leaving USE_MEASURED_INHERITED=False
    in sim.py — and the NEXT run then copied the already-mutated file as its
    backup and faithfully restored that, cementing the change. A sweep that
    silently switches off a shipped mechanism is worse than no sweep.

    Three fixes. Backups live OUTSIDE the tree, so a stray one cannot be
    mistaken for source. The tree must be clean before starting, so a
    previous corruption cannot be baked in. And restoration is registered
    with atexit and the terminating signals rather than relying on `finally`,
    which SIGKILL does not run — SIGKILL still cannot be caught, which is
    why the clean-tree precondition is the real guard.
    """
    import atexit
    import signal
    import subprocess as sp
    dirty = sp.run(["git", "diff", "--name-only", "--", "src/"], cwd=ROOT,
                   capture_output=True, text=True).stdout.split()
    if dirty:
        raise SystemExit(
            "refusing to run: uncommitted changes under src/ — a mutation "
            "sweep cannot tell your edits from its own.\n  " +
            "\n  ".join(dirty))
    live = {}

    def restore(*_a):
        for f, b in list(live.items()):
            if pathlib.Path(b).exists():
                shutil.move(b, f)
            live.pop(f, None)

    atexit.register(restore)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *a: (restore(), sys.exit(1)))
    return live


def main():
    import tempfile
    live = _guard()
    lines = []
    for path, pat, rep, label in MUTATIONS:
        f = ROOT / path
        fd, backup = tempfile.mkstemp(suffix=".mutbak")
        import os as _os
        _os.close(fd)
        shutil.copy(f, backup)
        live[str(f)] = backup
        try:
            s = f.read_text()
            new, n = re.subn(pat, rep, s, count=1, flags=re.M)
            if not n:
                lines.append(f"SKIP  {label}: pattern not found in {path}")
                continue
            f.write_text(new)
            for p in ROOT.rglob("__pycache__"):
                shutil.rmtree(p, ignore_errors=True)
            fails, dt = run_suite()
            if fails:
                lines.append(f"CAUGHT ({len(fails)})  {label}")
                for x in fails[:6]:
                    lines.append(f"           {x}")
            else:
                lines.append(f"*** SURVIVED ***  {label}  "
                             f"-- nothing guards this")
        finally:
            shutil.move(backup, f)
            live.pop(str(f), None)
        for p in ROOT.rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
        REPORT.write_text("\n".join(lines) + "\n")
        print(lines[-1] if lines else "", flush=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n=== done ===")


if __name__ == "__main__":
    main()
