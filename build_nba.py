"""Builds data/nba.json for the StatLine page.

Box scores come from the free sportsdataverse project (ESPN-based data).
Upcoming games and injuries come from ESPN's public JSON feeds.

Run: python build_nba.py
Needs: pip install sportsdataverse pandas pyarrow
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
SCORE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
INJ_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

POSMAP = {"PG": "G", "SG": "G", "G": "G", "Guard": "G", "Point Guard": "G", "Shooting Guard": "G",
          "SF": "F", "PF": "F", "F": "F", "Forward": "F", "Small Forward": "F", "Power Forward": "F",
          "C": "C", "Center": "C"}
CATS = [("points", "pts"), ("rebounds", "reb"), ("assists", "ast"), ("3-pointers made", "tpm")]
STATS = ["pts", "reb", "ast", "tpm"]


def pick(df, *names):
    for n in names:
        if n in df.columns:
            return n
    raise KeyError(f"None of {names} found in columns: {list(df.columns)[:40]}")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "statline/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_boxscores(seasons):
    from sportsdataverse.nba import load_nba_player_boxscore
    df = load_nba_player_boxscore(seasons=seasons)
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()
    return df


def season_for(today):
    """ESPN names a season by the year it ends, so 2026-27 is 2027."""
    return today.year + 1 if today.month >= 10 else today.year


def prepare(df):
    """Reduce the raw box score table to the columns we need."""
    if "season_type" in df.columns:
        df = df[pd.to_numeric(df["season_type"], errors="coerce") == 2]
    pos_col = pick(df, "athlete_position_abbreviation", "athlete_position_name")
    date_col = pick(df, "game_date", "game_date_time")
    b = pd.DataFrame({
        "game": df["game_id"],
        "season": pd.to_numeric(df["season"], errors="coerce"),
        "date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
        "team": df[pick(df, "team_abbreviation")],
        "opp": df[pick(df, "opponent_team_abbreviation")],
        "name": df[pick(df, "athlete_display_name")],
        "pos": df[pos_col].map(POSMAP),
        "min": pd.to_numeric(df["minutes"], errors="coerce"),
        "pts": pd.to_numeric(df["points"], errors="coerce"),
        "reb": pd.to_numeric(df["rebounds"], errors="coerce"),
        "ast": pd.to_numeric(df["assists"], errors="coerce"),
        "tpm": pd.to_numeric(df["three_point_field_goals_made"], errors="coerce"),
    })
    b = b[b["min"] > 0].copy()
    for c in STATS:
        b[c] = b[c].fillna(0)
    return b


def upcoming_games(today_et, days=3):
    games, names = [], {}
    for k in range(days):
        d = (today_et + timedelta(days=k)).strftime("%Y%m%d")
        try:
            data = get_json(SCORE_URL.format(d))
        except Exception as e:
            print("Could not load scoreboard", d, e)
            continue
        for ev in data.get("events", []):
            try:
                if ev["status"]["type"]["state"] != "pre":
                    continue
                comp = ev["competitions"][0]["competitors"]
                home = next(c for c in comp if c["homeAway"] == "home")["team"]
                away = next(c for c in comp if c["homeAway"] == "away")["team"]
                names[home.get("displayName")] = home["abbreviation"]
                names[away.get("displayName")] = away["abbreviation"]
                dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
                games.append({"away": away["abbreviation"], "home": home["abbreviation"],
                              "dt": dt, "when": f"{dt:%A} {dt:%H:%M}"})
            except Exception as e:
                print("Skipped an event:", e)
    games.sort(key=lambda g: g["dt"])
    return games, names


def load_injuries(names):
    out = {}
    try:
        data = get_json(INJ_URL)
    except Exception as e:
        print("Could not load injuries:", e)
        return out
    for t in data.get("injuries", []):
        abbr = names.get(t.get("displayName"))
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


def build(b, season, games, injuries):
    cur = b[b["season"] == season]
    gp = cur.groupby("opp")["game"].nunique()

    # Defense vs position (rank 1 = allows the most)
    defense = {}
    for pos in ["G", "F", "C"]:
        for label, col in CATS:
            tot = cur[cur["pos"] == pos].groupby("opp")[col].sum()
            per = (tot / gp).dropna()
            ranks = per.rank(ascending=False, method="min")
            for team in per.index:
                defense.setdefault(team, []).append(
                    [label, f"{per[team]:.1f}/game", int(ranks[team]), pos])

    # Team scores per game (sum of player points)
    gm = b.groupby(["game", "date", "team", "opp"])["pts"].sum().reset_index()

    def series(a, c):
        ga = gm[(gm["team"] == a) & (gm["opp"] == c)]
        gc = gm[(gm["team"] == c) & (gm["opp"] == a)][["game", "pts"]]
        m = ga.merge(gc, on="game", suffixes=("_a", "_c")).sort_values("date", ascending=False).head(3)
        meetings, wins = [], 0
        for _, r in m.iterrows():
            wins += r["pts_a"] > r["pts_c"]
            meetings.append([r["date"], f"{a} {int(r['pts_a'])}, {c} {int(r['pts_c'])}"])
        n = len(meetings)
        return {"summary": f"{a} won {int(wins)} of the last {n}" if n else "No recent meetings",
                "meetings": meetings}

    # Player logs for rotation players (last 7 games)
    players = []
    for name, g in cur.sort_values("date").groupby("name"):
        if len(g) < 3 or g["min"].mean() < 12:
            continue
        last = g.tail(7).iloc[::-1]   # most recent first
        players.append({
            "n": name, "t": g.iloc[-1]["team"], "m": float(g["min"].mean()),
            "a": [round(float(g[c].mean()), 1) for c in STATS],
            "g": [[r["date"], r["opp"]] + [int(r[c]) for c in STATS] for _, r in last.iterrows()],
        })
    top = {}
    for p in sorted(players, key=lambda p: -p["m"]):
        top.setdefault(p["t"], [])
        if len(top[p["t"]]) < 12:
            top[p["t"]].append(p)
    rotation = [p for t in top.values() for p in t]

    def history(team, opp):
        out = []
        for p in top.get(team, [])[:3]:
            h = b[(b["name"] == p["n"]) & (b["opp"] == opp)]
            if len(h):
                out.append([p["n"], f"{len(h)} games",
                            f"{h['pts'].mean():.0f} pts, {h['reb'].mean():.0f} reb, {h['ast'].mean():.0f} ast"])
        return out

    games_out = []
    for g in games:
        a, h = g["away"], g["home"]
        games_out.append({
            "away": a, "home": h, "when": g["when"],
            "defense": {"away": defense.get(a, []), "home": defense.get(h, [])},
            "injuries": {"away": injuries.get(a, []), "home": injuries.get(h, [])},
            "series": series(a, h),
            "history": {"away": history(a, h), "home": history(h, a)},
        })
    for p in rotation:
        p.pop("m", None)
    return games_out, rotation


def main():
    now_et = datetime.now(ET)
    season = season_for(now_et)
    b = prepare(load_boxscores([season - 2, season - 1, season]))
    games, names = upcoming_games(now_et)
    injuries = load_injuries(names)
    games_out, players = build(b, season, games, injuries)
    os.makedirs("data", exist_ok=True)
    with open("data/nba.json", "w") as f:
        json.dump({"updated": datetime.now(ET).astimezone(ZoneInfo("UTC")).isoformat(timespec="minutes"),
                   "season": season, "week": None, "games": games_out, "players": players}, f)
    print(f"Wrote {len(games_out)} games and {len(players)} players for season {season}")


if __name__ == "__main__":
    main()
