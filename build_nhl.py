"""Builds data/nhl.json for the StatLine page.

Games, box scores and rosters come from the NHL's public web API (api-web.nhle.com).
Injuries come from ESPN's public JSON feed.
Finished games are saved in data/nhl_cache.json so each run only downloads new ones.

Run: python build_nhl.py
Needs: pip install pandas
"""
import json
import os
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
API = "https://api-web.nhle.com/v1"
INJ_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
CACHE_PATH = "data/nhl_cache.json"
POS = {"C": "C", "L": "W", "R": "W", "W": "W", "D": "D", "G": "G"}

# Per-player columns kept for each game
COLS = ["goals", "assists", "sog", "blk", "hits", "saves"]


def get_json(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "statline/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1 + k)
    raise last


def dflt(x):
    """NHL API wraps many strings like {"default": "Boston"}."""
    if isinstance(x, dict):
        return x.get("default", "")
    return x or ""


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def minutes(toi):
    try:
        m, s = str(toi).split(":")
        return int(m) + int(s) / 60
    except Exception:
        return 0.0


def season_start(today):
    return today.year if today.month >= 9 else today.year - 1


def all_games(start, today):
    """Walk the schedule a week at a time. Returns {game_id: game dict}."""
    games = {}
    d = date(start, 10, 1)
    end = today + timedelta(days=4)
    while d <= end:
        try:
            data = get_json(f"{API}/schedule/{d.isoformat()}")
        except Exception as e:
            print("Could not load schedule", d, e)
            d += timedelta(days=7)
            continue
        for day in data.get("gameWeek", []):
            for g in day.get("games", []):
                if g.get("gameType") == 2:
                    games[g["id"]] = g
        d += timedelta(days=7)
    return games


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def parse_box(gid, data):
    """Turn one boxscore response into a cache record."""
    away, home = data["awayTeam"]["abbrev"], data["homeTeam"]["abbrev"]
    rows = []
    stats = data.get("playerByGameStats", {})
    for side, team, opp in (("awayTeam", away, home), ("homeTeam", home, away)):
        grp = stats.get(side, {})
        for kind in ("forwards", "defense"):
            for p in grp.get(kind, []):
                toi = minutes(p.get("toi"))
                if toi <= 0:
                    continue
                rows.append([p["playerId"], dflt(p.get("name")), POS.get(p.get("position"), "W"), team, opp,
                             p.get("goals", 0), p.get("assists", 0), p.get("sog", 0),
                             p.get("blockedShots", 0), p.get("hits", 0), 0, round(toi, 1)])
        for p in grp.get("goalies", []):
            toi = minutes(p.get("toi"))
            if toi <= 0:
                continue
            saves = p.get("saves")
            if saves is None:
                try:
                    saves = int(str(p.get("saveShotsAgainst", "0/0")).split("/")[0])
                except Exception:
                    saves = 0
            rows.append([p["playerId"], dflt(p.get("name")), "G", team, opp, 0, 0, 0, 0, 0, saves, round(toi, 1)])
    return {"d": data.get("gameDate", ""), "t": [away, home],
            "s": [data["awayTeam"].get("score", 0), data["homeTeam"].get("score", 0)], "r": rows}


def roster_names(teams):
    names = {}
    for t in teams:
        try:
            data = get_json(f"{API}/roster/{t}/current")
        except Exception as e:
            print("Could not load roster", t, e)
            continue
        for grp in ("forwards", "defensemen", "goalies"):
            for p in data.get(grp, []):
                names[p["id"]] = f"{dflt(p.get('firstName'))} {dflt(p.get('lastName'))}".strip()
    return names


def load_injuries(team_names):
    """team_names: {abbrev: 'Boston Bruins'}"""
    out = {}
    try:
        data = get_json(INJ_URL)
    except Exception as e:
        print("Could not load injuries:", e)
        return out
    lookup = {norm(v): k for k, v in team_names.items()}
    for t in data.get("injuries", []):
        name = norm(t.get("displayName"))
        abbr = lookup.get(name) or next((k for n, k in lookup.items() if n.endswith(name.split(" ")[-1])), None)
        if not abbr:
            continue
        rows = []
        for i in t.get("injuries", []):
            ath = i.get("athlete") or {}
            pos = (ath.get("position") or {}).get("abbreviation", "")
            detail = ((i.get("details") or {}).get("type") or "undisclosed").lower()
            rows.append([ath.get("displayName", "Unknown"), pos, i.get("status", ""), detail])
        rows.sort(key=lambda r: 0 if r[2] == "Out" else 1)
        out[abbr] = rows[:8]
    return out


def build(cache, upcoming, names_by_id, injuries):
    cols = ["pid", "name", "pos", "team", "opp"] + COLS + ["toi"]
    recs = []
    for gid, g in cache.items():
        for r in g["r"]:
            recs.append([gid, g["d"]] + r)
    df = pd.DataFrame(recs, columns=["game", "date"] + cols)
    df["points"] = df["goals"] + df["assists"]
    df["name"] = [names_by_id.get(p, n) for p, n in zip(df["pid"], df["name"])]
    sk = df[df["pos"].isin(["C", "W", "D"])]
    gp = df.groupby("opp")["game"].nunique()

    # Defense vs position (rank 1 = allows the most)
    CATS = [("goals", "goals"), ("assists", "assists"), ("points", "points"), ("shots on goal", "sog")]
    defense = {}
    for pos in ["C", "W", "D"]:
        for label, col in CATS:
            tot = sk[sk["pos"] == pos].groupby("opp")[col].sum()
            per = (tot / gp).dropna()
            ranks = per.rank(ascending=False, method="min")
            for team in per.index:
                defense.setdefault(team, []).append([label, f"{per[team]:.1f}/game", int(ranks[team]), pos])

    def series(a, b):
        meets = []
        for gid, g in cache.items():
            if set(g["t"]) == {a, b}:
                sa = g["s"][g["t"].index(a)]
                sb = g["s"][g["t"].index(b)]
                meets.append((g["d"], sa, sb))
        meets.sort(reverse=True)
        meets = meets[:3]
        wins = sum(1 for _, x, y in meets if x > y)
        return {"summary": f"{a} won {wins} of {len(meets)} this season" if meets else "No meetings yet this season",
                "meetings": [[d, f"{a} {x}, {b} {y}"] for d, x, y in meets]}

    # Player logs (rotation players + goalies)
    players, top = [], {}
    for pid, g in df.sort_values("date").groupby("pid"):
        last = g.iloc[-1]
        is_g = last["pos"] == "G"
        if len(g) < (2 if is_g else 3) or (not is_g and g["toi"].mean() < 12):
            continue
        rows = g.tail(7).iloc[::-1]
        p = {"n": last["name"], "t": last["team"], "p": last["pos"], "m": float(g["toi"].mean()), "gk": bool(is_g),
             "a": [round(float(g[c].mean()), 1) for c in ["goals", "assists", "points", "sog", "blk", "hits", "saves"]],
             "g": [[r["date"], r["opp"], int(r["goals"]), int(r["assists"]), int(r["points"]), int(r["sog"]),
                    int(r["blk"]), int(r["hits"]), int(r["saves"])] for _, r in rows.iterrows()]}
        players.append(p)
    keep = []
    for p in sorted(players, key=lambda p: -p["m"]):
        bucket = top.setdefault(p["t"], {"sk": [], "gk": []})
        key = "gk" if p["gk"] else "sk"
        if len(bucket[key]) < (2 if p["gk"] else 14):
            bucket[key].append(p)
            keep.append(p)

    def history(team, opp):
        out = []
        for p in top.get(team, {"sk": []})["sk"][:3]:
            h = df[(df["name"] == p["n"]) & (df["opp"] == opp)]
            if len(h):
                out.append([p["n"], f"{len(h)} games", f"{h['points'].mean():.1f} pts, {h['sog'].mean():.1f} SOG"])
        return out

    games_out = []
    for g in upcoming:
        a, h = g["away"], g["home"]
        games_out.append({
            "away": a, "home": h, "when": g["when"],
            "defense": {"away": defense.get(a, []), "home": defense.get(h, [])},
            "injuries": {"away": injuries.get(a, []), "home": injuries.get(h, [])},
            "series": series(a, h),
            "history": {"away": history(a, h), "home": history(h, a)},
        })
    for p in keep:
        p.pop("m", None)
        p.pop("gk", None)
    return games_out, keep


def main():
    now = datetime.now(ET)
    start = season_start(now.date())
    sched = all_games(start, now.date())

    cache = load_cache()
    new = 0
    for gid, g in sched.items():
        if g.get("gameState") in ("FINAL", "OFF") and str(gid) not in cache:
            try:
                cache[str(gid)] = parse_box(gid, get_json(f"{API}/gamecenter/{gid}/boxscore"))
                new += 1
            except Exception as e:
                print("Skipped game", gid, e)
    print(f"Downloaded {new} new games, {len(cache)} in total")

    upcoming, team_names = [], {}
    for gid, g in sched.items():
        for side in ("awayTeam", "homeTeam"):
            t = g[side]
            team_names[t["abbrev"]] = f"{dflt(t.get('placeName'))} {dflt(t.get('commonName'))}".strip()
        if g.get("gameState") in ("FUT", "PRE") and g.get("startTimeUTC"):
            dt = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")).astimezone(ET)
            if dt.date() <= now.date() + timedelta(days=3):
                upcoming.append({"away": g["awayTeam"]["abbrev"], "home": g["homeTeam"]["abbrev"],
                                 "dt": dt, "when": f"{dt:%A} {dt:%H:%M}"})
    upcoming.sort(key=lambda g: g["dt"])

    names_by_id = roster_names(sorted(team_names))
    injuries = load_injuries(team_names)

    games_out, players = build(cache, upcoming, names_by_id, injuries)
    os.makedirs("data", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    with open("data/nhl.json", "w") as f:
        json.dump({"updated": datetime.now(ET).astimezone(ZoneInfo("UTC")).isoformat(timespec="minutes"),
                   "season": start, "week": None, "games": games_out, "players": players},
                  f, separators=(",", ":"))
    print(f"Wrote {len(games_out)} games and {len(players)} players for the {start} season")


if __name__ == "__main__":
    main()
