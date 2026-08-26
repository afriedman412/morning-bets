"""PRESEASON 2026 starting-pitcher rankings, transcribed with provenance.

The point of these is that they are DATED BEFORE A PITCH WAS THROWN, so
using them to predict July and August leaks nothing. That is the whole
reason an in-season ranking is useless here: Pitcher List publishes the same
top 100 every week, and the 25 August edition knows how the season went.

Each list is a human consensus of what a pitcher is EXPECTED to be, which is
the quantity nothing in the database contains. Rates say what he has done;
these say what people thought he would do.

    RAZZBALL      2026-02-16   100 SP, complete
    FANTASYPROS   2026-03-22    86 SP, complete, tiered
    FANGRAPHS     2026-03-20    PARTIAL — the fetch returned gaps in the
                                rank sequence (38 then 41, 43, 46 ...), so
                                absence from this list does NOT mean
                                unranked and it must never drive the
                                unranked penalty. Kept because where it
                                does rank a man it agrees closely, which is
                                a check on the other two.

NAMES ARE AS PUBLISHED and do not all match MLB's spelling — 'Tatsyui Imai'
for Tatsuya Imai, accents present in one list and absent in another. Joining
on raw strings silently drops those pitchers, which is the same
`'D-backs'` versus `'Arizona Diamondbacks'` bug that cost this project four
fields. `normalise()` exists for that and the join reports its miss rate.
"""
from __future__ import annotations

import unicodedata

SOURCES = {
    "razzball": {
        "date": "2026-02-16", "complete": True,
        "url": "https://razzball.com/top-100-starting-pitchers-for-2026-"
               "for-the-living-baseball-heads/",
    },
    "fantasypros": {
        "date": "2026-03-22", "complete": True,
        "url": "https://www.fantasypros.com/2026/03/fantasy-baseball-primer-"
               "starting-pitchers-rankings-tiers-2026/",
    },
    "fangraphs": {
        "date": "2026-03-20", "complete": False,
        "url": "https://fantasy.fangraphs.com/starting-pitcher-2026-fantasy-"
               "rankings/",
    },
}

RAZZBALL = """Tarik Skubal|Paul Skenes|Garrett Crochet|Yoshinobu Yamamoto|
Cristopher Sanchez|Bryan Woo|Logan Webb|Logan Gilbert|Hunter Greene|
Hunter Brown|Cole Ragans|Jacob deGrom|Max Fried|George Kirby|Kyle Bradish|
Chris Sale|Dylan Cease|Joe Ryan|Framber Valdez|Freddy Peralta|Shohei Ohtani|
Jesus Luzardo|Tyler Glasnow|Kevin Gausman|Eury Perez|Sonny Gray|
Nolan McLean|Chase Burns|Nathan Eovaldi|Emmett Sheehan|Trey Yesavage|
Nick Lodolo|Brandon Woodruff|Zack Wheeler|Blake Snell|Jacob Misiorowski|
Nick Pivetta|Spencer Strider|Robbie Ray|Michael King|Cam Schlittler|
Trevor Rogers|Pablo Lopez|Ryan Pepiot|Shota Imanaga|Bubba Chandler|
Gavin Williams|Ranger Suarez|Tatsyui Imai|Drew Rasmussen|Matthew Boyd|
Edward Cabrera|Shane Bieber|Luis Castillo|Jack Flaherty|Tanner Bibee|
Andrew Abbott|Merrill Kelly|Sandy Alcantara|Mackenzie Gore|Carlos Rodon|
Shane Baz|Logan Henderson|Joe Musgrove|Kris Bubic|Quinn Priester|Zac Gallen|
Joey Cantillo|Shane Smith|Noah Cameron|Roki Sasaki|Jack Leiter|
Grayson Rodriguez|Ryan Weathers|David Peterson|Cody Ponce|Ryne Nelson|
Cade Horton|Clay Holmes|Shane McClanahan|Will Warren|Seth Lugo|Gerrit Cole|
Hurston Waldrep|Casey Mize|Brayan Bello|Kodai Senga|Mike Burrows|
Mitch Keller|Sean Manaea|Aaron Nola|Connelly Early|Zebby Matthews|
Jonah Tong|Andrew Painter|Payton Tolle|Bryce Miller|Braxton Ashcraft|
Michael Wacha|Parker Messick"""

FANTASYPROS = """Tarik Skubal|Garrett Crochet|Paul Skenes|Cristopher Sanchez|
Yoshinobu Yamamoto|Hunter Brown|Jacob deGrom|Max Fried|Chris Sale|Bryan Woo|
Logan Gilbert|Cole Ragans|Nolan McLean|Freddy Peralta|Eury Perez|
George Kirby|Joe Ryan|Dylan Cease|Jesus Luzardo|Kyle Bradish|Spencer Strider|
Cam Schlittler|Drew Rasmussen|Sandy Alcantara|Framber Valdez|Nick Pivetta|
Shota Imanaga|Blake Snell|Kevin Gausman|Tyler Glasnow|Brandon Woodruff|
Jacob Misiorowski|Sonny Gray|Nick Lodolo|Emmet Sheehan|Zack Wheeler|
Cade Horton|Trevor Rogers|Bubba Chandler|Robbie Ray|Luis Castillo|
Ryne Nelson|Nathan Eovaldi|Tatsuya Imai|Michael King|Ryan Pepiot|
Gavin Williams|Ranger Suarez|Tanner Bibee|MacKenzie Gore|Edward Cabrera|
Shane Baz|Matthew Boyd|Kris Bubic|Zac Gallen|Jack Leiter|Bryce Miller|
Connelly Early|Max Meyer|Chad Patrick|Parker Messick|Aaron Nola|
Jack Flaherty|Carlos Rodon|Shane McClanahan|Shane Bieber|Merrill Kelly|
Roki Sasaki|Trey Yesavage|Ryan Weathers|Andrew Painter|Andrew Abbott|
Kodai Senga|Joey Cantillo|Noah Cameron|Casey Mize|Zach Eflin|
Braxton Ashcraft|Sean Manaea|Cody Ponce|Mike Burrows|Jose Soriano|
Ian Seymour|Cade Cavalli|Michael Wacha|Shane Smith"""

#: (name, published rank). Gapped — see the module docstring.
FANGRAPHS = [
    ("Tarik Skubal", 1), ("Paul Skenes", 2), ("Garrett Crochet", 3),
    ("Yoshinobu Yamamoto", 4), ("Cristopher Sanchez", 5), ("Max Fried", 6),
    ("Chris Sale", 7), ("Logan Gilbert", 8), ("Bryan Woo", 9),
    ("Cole Ragans", 10), ("Hunter Brown", 11), ("George Kirby", 12),
    ("Shohei Ohtani", 13), ("Jacob deGrom", 14), ("Logan Webb", 15),
    ("Freddy Peralta", 16), ("Kyle Bradish", 17), ("Nick Pivetta", 18),
    ("Jesus Luzardo", 19), ("Eury Perez", 20), ("Drew Rasmussen", 21),
    ("Tyler Glasnow", 22), ("Framber Valdez", 23), ("Sandy Alcantara", 24),
    ("Dylan Cease", 25), ("Ryan Pepiot", 26), ("Joe Ryan", 27),
    ("Michael King", 28), ("Emmet Sheehan", 29), ("Trevor Rogers", 30),
    ("Tatsuya Imai", 31), ("Kevin Gausman", 32), ("Nolan McLean", 33),
    ("Cade Horton", 34), ("Cam Schlittler", 35), ("Nick Lodolo", 36),
    ("Nathan Eovaldi", 37), ("Jacob Misiorowski", 38),
    ("Gavin Williams", 41), ("Luis Castillo", 43), ("Sonny Gray", 46),
    ("Brandon Woodruff", 47), ("Zack Wheeler", 48), ("Ranger Suarez", 52),
    ("Spencer Strider", 55), ("Chase Burns", 58), ("Zac Gallen", 60),
    ("Andrew Abbott", 62), ("Blake Snell", 75), ("Bryce Miller", 87),
    ("Carlos Rodon", 97), ("Shane Smith", 104), ("Shane Bieber", 131),
]


def normalise(name: str) -> str:
    """Fold accents, drop punctuation, lowercase. 'Jesús Luzardo' -> jesus
    luzardo, so a list that prints accents joins one that does not."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum() or c == " ").strip()


def _seq(blob: str) -> dict:
    names = [n.strip() for n in blob.replace("\n", "").split("|") if n.strip()]
    return {normalise(n): i + 1 for i, n in enumerate(names)}


#: Hand-corrected spellings. Each is a name one list prints differently from
#: MLB's own roster feed; without these the pitcher is silently dropped.
ALIASES = {
    "tatsyui imai": "tatsuya imai",
    "emmett sheehan": "emmet sheehan",
}


def ranks() -> dict:
    """{source: {normalised name: rank}}."""
    out = {"razzball": _seq(RAZZBALL), "fantasypros": _seq(FANTASYPROS),
           "fangraphs": {normalise(n): r for n, r in FANGRAPHS}}
    for src in out.values():
        for wrong, right in ALIASES.items():
            if wrong in src:
                src[right] = src.pop(wrong)
    return out


if __name__ == "__main__":
    r = ranks()
    for k, v in r.items():
        meta = SOURCES[k]
        print(f"  {k:<14}{meta['date']}  {len(v):>4} pitchers"
              f"{'' if meta['complete'] else '   PARTIAL'}")
    common = set(r["razzball"]) & set(r["fantasypros"])
    print(f"\n  {len(common)} pitchers on both complete lists")
    xs = [r["razzball"][n] for n in common]
    ys = [r["fantasypros"][n] for n in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = (sum((x - mx) ** 2 for x in xs) / len(xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / len(ys)) ** 0.5
    print("  they agree at r "
          f"{sum((x-mx)*(y-my) for x, y in zip(xs, ys))/(len(xs)*sx*sy):+.3f}")
