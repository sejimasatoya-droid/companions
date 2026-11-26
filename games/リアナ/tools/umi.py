#!/usr/bin/env python3
"""航海の道具（リアナ）。船・海・港・時計をまとめて動かす。

  海の上
    python tools/umi.py status                 … いまの船と荷と日付
    python tools/umi.py sail 南西 [日数]        … その方角へ帆を張る（北 北東 東 南東 南 南西 西 北西 / n ne e se s sw w nw）
    python tools/umi.py goto 44 26 [日数]       … 海図に描いてある海だけを通って、そこへ向かう（道の省略用）
    python tools/umi.py wait [日数]             … 錨を下ろす・漂う・港で休む
    python tools/umi.py land                    … 隣の岸に小舟で上がる（水・新しい食べ物・調べもの）
    python tools/umi.py look                    … まわりのマスと風
  港で
    python tools/umi.py enter                   … 隣の港に入る
    python tools/umi.py market                  … 相場を見る
    python tools/umi.py buy 胡椒 10 / sell 胡椒 10
    python tools/umi.py supply 水 30 / supply 食料 30
    python tools/umi.py hire 10 / fire 3        … 水夫を雇う・暇を出す
    python tools/umi.py pay                     … たまった給金を払う
    python tools/umi.py repair [点]             … 船体を直す
    python tools/umi.py leave                   … 港を出る
  記録
    python tools/umi.py init                    … 遊び始めの状態を作る（一度だけ）
    python tools/umi.py map                     … 瀬島の海図（海図/海図.md）を書き出す
                                                （海図/海図.svg の絵は、どのコマンドのあとでも自動で書き直す）
    python tools/umi.py gmmap                   … 隠れたところも全部（GM だけが見る）
    python tools/umi.py clocks                  … 時計（GM だけが見る）
    python tools/umi.py set 士気 60             … 状態の値を手で直す（GM の裁定。判断記録に理由を書く）
    python tools/umi.py who                     … 人物の生死・居場所・人物どうしの思い（GM だけが見る）
    python tools/umi.py npc 名 dead / npc 名 where 港 … 士官が死んだ・船を降りた（GM）
    python tools/umi.py rel 甲 乙 -3            … 甲から乙への思いを動かす（GM）
    python tools/umi.py find 名前               … 発見物を「見つけた」にする（上陸して調べて成功したとき）
    python tools/umi.py report                  … リアナの地理院で、見つけたものを報告する

出力のうち [GM] で始まる行は、瀬島に見せない。
出目と結果は gm/出目.log に自動で残る。
"""
import json, math, pathlib, random, sys, datetime
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEA = ROOT / "gm" / "海.json"
PORTS = ROOT / "gm" / "港.json"
MARKET = ROOT / "gm" / "相場.json"
CLOCKS = ROOT / "gm" / "時計.json"
STATE = ROOT / "状態.json"
PUBMAP = ROOT / "海図" / "海図.md"
PUBSVG = ROOT / "海図" / "海図.svg"
LOG = ROOT / "gm" / "出目.log"
NPCF = ROOT / "gm" / "NPC.json"

DIRS = [("北", 0, -1), ("北東", 1, -1), ("東", 1, 0), ("南東", 1, 1),
        ("南", 0, 1), ("南西", -1, 1), ("西", -1, 0), ("北西", -1, -1)]
ALIAS = {"n": 0, "ne": 1, "e": 2, "se": 3, "s": 4, "sw": 5, "w": 6, "nw": 7}
for i, (nm, _, _) in enumerate(DIRS):
    ALIAS[nm] = i

SHIPS = {
    # 型:        船体, 速さ, 積載, 定員, 最低, 砲, 逆風, 値
    "小型船":    dict(hull=30, speed=5, hold=40, crew=20, min=8, guns=2, upwind=0.0, price=1500),
    "キャラベル": dict(hull=50, speed=6, hold=90, crew=35, min=14, guns=6, upwind=0.2, price=4000),
    "キャラック": dict(hull=80, speed=5, hold=220, crew=70, min=28, guns=12, upwind=0.0, price=9000),
    "ガレオン":  dict(hull=110, speed=5, hold=260, crew=110, min=40, guns=24, upwind=0.0, price=16000),
}

out_lines = []


def say(s=""):
    out_lines.append(s)
    print(s)


def flush_log(cmd):
    if not out_lines:
        return
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.datetime.now():%Y-%m-%d %H:%M}  umi.py {' '.join(cmd)}\n")
        for l in out_lines:
            f.write(l + "\n")


def load(p, default=None):
    if not p.exists():
        if default is not None:
            return default
        sys.exit(f"ない：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def roll(n=2, s=6):
    return [random.randint(1, s) for _ in range(n)]


def check(mod, target, label):
    a, b = roll()
    t = a + b + mod
    if a == b == 6:
        r = "会心"
    elif a == b == 1:
        r = "大失敗"
    elif t >= target:
        r = "成功"
    elif t == target - 1:
        r = "紙一重"
    else:
        r = "失敗"
    say(f"  判定〔{label}〕2d6[{a},{b}]{mod:+d} = {t} / 目標{target} → {r}")
    return r


# ---------------------------------------------------------------- 海
class Sea:
    def __init__(self):
        d = load(SEA)
        self.w, self.h = d["w"], d["h"]
        self.rows = [list(r) for r in d["rows"]]
        self.ports = d["ports"]
        self.finds = d["finds"]
        self.zones = d["zones"]
        self.port_at = {(p["x"], p["y"]): p for p in self.ports}

    def cell(self, x, y):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return "#"
        return self.rows[y][x]

    def zone(self, x, y):
        for z in self.zones:
            if z["x0"] <= x < z["x1"] and z["y0"] <= y < z["y1"]:
                return z
        return {"name": "大洋", "danger": 0, "storm": 1}

    def sea(self, x, y):
        return self.cell(x, y) in "~.:m"


def month_of(st):
    return st["date"]["m"]


def date_str(st):
    d = st["date"]
    return f"王国暦 {d['y']} 年 {d['m']} 月 {d['d']} 日"


def advance_date(st):
    d = st["date"]
    d["d"] += 1
    if d["d"] > 30:
        d["d"] = 1
        d["m"] += 1
        if d["m"] > 12:
            d["m"] = 1
            d["y"] += 1


def season_storm(zone, month):
    n = zone["name"]
    if n == "翠の諸島の海" and month in (8, 9, 10):
        return 3
    if n == "嵐の岬の沖":
        return 3 if month in (5, 6, 7, 8) else 1.2
    if n == "北の大洋" and month in (11, 12, 1, 2):
        return 2.5
    if n == "東の海" and month in (5, 6, 9, 10):
        return 2
    return 1


def prevailing(x, y, month):
    """風の吹いていく方角（0=北へ吹く …）と、凪の起きやすさ。"""
    if x >= 70 and y >= 22:  # 東の海の季節風
        if month in (5, 6, 7, 8, 9):
            return 1, 0.08
        if month in (11, 12, 1, 2, 3):
            return 5, 0.08
        return None, 0.2
    if y < 14:
        return 2, 0.08          # 偏西風：東へ吹く
    if y < 30:
        return 5, 0.06          # 北東の貿易風：南西へ吹く
    if y < 34:
        return None, 0.45       # 無風帯
    if y < 42:
        return 7, 0.08          # 南東の貿易風：北西へ吹く
    return 2, 0.03              # 吠える南：東へ強く


def make_wind(sea, x, y, st):
    m = month_of(st)
    pre, calm = prevailing(x, y, m)
    if sea.cell(x, y) == "m":
        calm = 0.85
    r = random.random()
    if pre is None:
        d = random.randrange(8)
    elif r < 0.62:
        d = pre
    elif r < 0.85:
        d = (pre + random.choice((-1, 1))) % 8
    else:
        d = random.randrange(8)
    z = sea.zone(x, y)
    storm_p = 0.025 * z["storm"] * season_storm(z, m)
    if y >= 42:
        storm_p += 0.03
    s = random.random()
    if st.get("storm_left", 0) > 0 and sea.cell(x, y) != "m":
        st["storm_left"] -= 1
        return {"dir": d, "str": "嵐"}
    if s < calm:
        strength = "凪"
    elif s < calm + storm_p:
        strength = "嵐"
    else:
        s2 = random.random()
        strength = "弱" if s2 < 0.28 else ("並" if s2 < 0.78 else "強")
        if y >= 42 and strength == "弱":
            strength = "強"
    return {"dir": d, "str": strength}


STRF = {"凪": 0.12, "弱": 0.6, "並": 1.0, "強": 1.25, "嵐": 0.7}
ANGF = [1.0, 1.1, 0.9, 0.45, 0.15]


def wind_factor(heading, wind, ship):
    diff = abs(heading - wind["dir"]) % 8
    diff = min(diff, 8 - diff)
    f = ANGF[diff]
    if diff >= 3:
        f += SHIPS[ship["type"]]["upwind"]
    return f * STRF[wind["str"]]


def wind_str(w):
    frm = DIRS[(w["dir"] + 4) % 8][0]
    return f"{frm}の風・{w['str']}" if w["str"] != "凪" else "凪"


# ---------------------------------------------------------------- 状態
def ship_spec(st):
    return SHIPS[st["ship"]["type"]]


def cargo_used(st):
    return sum(st["cargo"].values()) + math.ceil(st["water"]) + math.ceil(st["food"])


def sight_radius(st, wind):
    r = 2
    if wind["str"] in ("嵐",) or st.get("weather") == "霧":
        r = 1
    elif st["captain"].get("目", 0) >= 2:
        r = 3
    return r


def reveal(sea, st, x, y, r):
    news = []
    known = set(map(tuple, st["known"]))
    for yy in range(y - r, y + r + 1):
        for xx in range(x - r, x + r + 1):
            if 0 <= xx < sea.w and 0 <= yy < sea.h and (xx, yy) not in known:
                known.add((xx, yy))
                c = sea.cell(xx, yy)
                p = sea.port_at.get((xx, yy))
                if p and p["name"] not in st["ports_known"]:
                    st["ports_known"].append(p["name"])
                    news.append(f"★ 港が見えた：{p['name']}（{xx},{yy}）")
                for f in sea.finds:
                    if f["x"] == xx and f["y"] == yy and f["how"] == "sight" and f["name"] not in st["found"]:
                        st["found"][f["name"]] = {"date": date_str(st), "reported": False}
                        news.append(f"★ 発見：{f['name']}（{xx},{yy}）")
                        st["morale"] = min(100, st["morale"] + 5)
                if c == "#" and not any(n.startswith("陸") for n in news):
                    news.append(f"陸が見えた（{xx},{yy} のあたり）")
    st["known"] = [list(k) for k in sorted(known)]
    return news


def daily_needs(st, sea, x, y, wind):
    """一日ぶんの水と食料、士気、病。止まる理由を返す。"""
    stop = []
    crew = st["crew"]
    need = crew / 30
    rain = wind["str"] in ("嵐",) or (wind["str"] != "凪" and random.random() < 0.08)
    if rain and st["port"] is None:
        gain = random.randint(1, 6)
        cap = ship_spec(st)["hold"] - cargo_used(st)
        gain = max(0, min(gain, cap))
        if gain:
            st["water"] += gain
            say(f"  雨。水を {gain} 樽ためた")
    st["water"] -= need
    st["food"] -= need
    if st["water"] < 0:
        st["water"] = 0
        st["thirst"] = st.get("thirst", 0) + 1
        st["morale"] -= 8
        lost = max(1, round(crew * random.uniform(0.02, 0.06) * st["thirst"]))
        st["crew"] -= lost
        say(f"  水がない（{st['thirst']} 日目）。{lost} 人が倒れた。士気 −8")
        stop.append("水")
    else:
        st["thirst"] = 0
    if st["food"] < 0:
        st["food"] = 0
        st["hunger"] = st.get("hunger", 0) + 1
        st["morale"] -= 4
        if st["hunger"] > 3:
            lost = max(1, round(crew * random.uniform(0.01, 0.03)))
            st["crew"] -= lost
            say(f"  食べ物がない（{st['hunger']} 日目）。{lost} 人が死んだ。士気 −4")
        else:
            say(f"  食べ物がない（{st['hunger']} 日目）。士気 −4")
        stop.append("食料")
    else:
        st["hunger"] = 0
    # 士気：長い航海は削る
    st["days_at_sea"] += 1
    ds = st["days_at_sea"]
    if ds > 30:
        st["morale"] -= 2
    elif ds > 14:
        st["morale"] -= 1
    # 給金
    st["wages_due"] += crew * 0.1
    st["days_unpaid"] += 1
    if st["days_unpaid"] > 45 and st["days_unpaid"] % 5 == 0:
        st["morale"] -= 3
        say("  給金が払われていないと、甲板でささやく声。士気 −3")
    # 壊血病
    st["days_no_fresh"] += 1
    if st["days_no_fresh"] > 40 and st["cargo"].get("柑橘", 0) <= 0:
        p = min(0.5, (st["days_no_fresh"] - 40) * 0.02 + 0.05)
        if random.random() < p:
            k = random.randint(1, 3)
            st["crew"] -= k
            st["sick"] = st.get("sick", 0) + random.randint(1, 4)
            say(f"  歯ぐきから血を流す者がふえる。{k} 人が死んだ（壊血病）")
            say(f"[GM] 壊血病：新鮮な食べ物から {st['days_no_fresh']} 日")
    # 水夫が足りない
    if st["crew"] < ship_spec(st)["min"]:
        stop.append("人手")
    # 士気の危機
    st["morale"] = max(0, min(100, st["morale"]))
    if st["morale"] < 20 and st["port"] is None:
        c = st["captain"]
        r = check(c.get("胆", 0) + c.get("指揮", 0) + officer_bonus(st, "水夫長"), 10, "不穏を抑える（胆＋指揮）")
        if r == "大失敗" or (r == "失敗" and st["morale"] < 8):
            say("[GM] 反乱が起きる。gm/出会い表.md の「反乱」を読む")
            stop.append("反乱")
        elif r in ("失敗",):
            say("[GM] 不穏：水夫たちが集まって話している。代表が船長に詰め寄る（gm/出会い表.md「不穏」）")
            stop.append("不穏")
    return stop


def officer_bonus(st, role):
    for o in st.get("officers", []):
        if o.get("role") == role and o.get("alive", True):
            return o.get("bonus", 0)
    return 0


ENCOUNTERS = [
    # 名前, 重み（ふつうの海）, 危ない海での重み
    ("商船", 5, 2), ("海賊", 1, 5), ("他国の船", 2, 2), ("漂流物", 2, 1), ("海の生き物", 2, 1),
    ("鳥と雲", 3, 1), ("船の傷み", 2, 1), ("病", 1, 1), ("流れ者", 1, 1),
]


def encounter(sea, st, x, y):
    z = sea.zone(x, y)
    p = 0.07 + 0.04 * z["danger"]
    if random.random() >= p:
        return None
    danger = z["danger"] >= 2
    known_waters = x >= 44 and y <= 20
    items = []
    for name, wn, wd in ENCOUNTERS:
        wgt = wd if danger else wn
        if name == "商船" and not known_waters and z["name"] != "東の海":
            wgt = 1 if not danger else 0
        if name == "鳥と雲" and known_waters:
            wgt = 0
        items.append((name, wgt))
    tot = sum(w for _, w in items)
    r = random.uniform(0, tot)
    for name, wgt in items:
        r -= wgt
        if r <= 0:
            return name
    return items[-1][0]


def land_hint(sea, x, y):
    best = None
    for yy in range(y - 6, y + 7):
        for xx in range(x - 6, x + 7):
            if sea.cell(xx, yy) == "#" and 0 <= xx < sea.w and 0 <= yy < sea.h:
                d = max(abs(xx - x), abs(yy - y))
                if best is None or d < best[0]:
                    best = (d, xx, yy)
    if not best:
        return None
    dx, dy = best[1] - x, best[2] - y
    ang = math.atan2(dx, -dy)
    idx = round(ang / (math.pi / 4)) % 8
    return DIRS[idx][0], best[0]


def one_day(sea, st, heading=None, path=None):
    """一日進める。止まる理由のリストを返す。"""
    x, y = st["pos"]
    crew_before = st["crew"]
    wind = make_wind(sea, x, y, st)
    st["wind"] = wind
    advance_date(st)
    say(f"【{date_str(st)}】{wind_str(wind)}　いま ({x},{y}) {sea.zone(x, y)['name']}")
    stop = []
    spec = ship_spec(st)
    moved = 0
    if heading is not None or path:
        hands = min(1.0, st["crew"] / max(1, spec["crew"] * 0.6))
        mast = 0.6 if st["ship"].get("mast_broken") else 1.0
        h0 = heading if heading is not None else dir_to(st["pos"], path[0])
        pts = spec["speed"] * wind_factor(h0, wind, st["ship"]) * hands * mast
        pts *= 1 + 0.04 * st["captain"].get("航海", 0)
        pts += random.uniform(-0.5, 0.5)
        steps_budget = pts / 4
        while steps_budget > 0:
            if path:
                if not path:
                    break
                nx, ny = path[0]
                h = dir_to((x, y), (nx, ny))
            else:
                h = heading
                nx, ny = x + DIRS[h][1], y + DIRS[h][2]
            cost = 1.4 if DIRS[h][1] and DIRS[h][2] else 1.0
            if steps_budget < cost:
                if random.random() > steps_budget / cost:
                    break
            steps_budget -= cost
            if not sea.sea(nx, ny):
                stop.append("陸")
                say(f"  この先（{nx},{ny}）は陸。帆を下ろす")
                break
            x, y = nx, ny
            moved += 1
            if path:
                path.pop(0)
            c = sea.cell(x, y)
            if c == ":":
                r = check(st["captain"].get("目", 0) + st["captain"].get("航海", 0) + officer_bonus(st, "航海士"), 9,
                          "浅瀬を避ける（目＋航海）")
                if r in ("失敗", "大失敗"):
                    dmg = sum(roll(2)) + (4 if r == "大失敗" else 0)
                    st["ship"]["hull"] -= dmg
                    say(f"  暗礁に船底をこする。船体 −{dmg}（{st['ship']['hull']}/{spec['hull']}）")
                    stop.append("暗礁")
                    break
                if r == "紙一重":
                    dmg = random.randint(1, 6)
                    st["ship"]["hull"] -= dmg
                    say(f"  かすった。船体 −{dmg}")
            news = reveal(sea, st, x, y, sight_radius(st, wind))
            for n in news:
                say("  " + n)
                if n.startswith("★"):
                    stop.append("発見")
            if any(n.startswith("★") for n in news):
                break
            if path is not None and not path:
                stop.append("着いた")
                break
    else:
        news = reveal(sea, st, x, y, sight_radius(st, wind))
        for n in news:
            say("  " + n)
    st["pos"] = [x, y]
    if moved:
        say(f"  {moved} マス進んで ({x},{y})")
    # 嵐
    if wind["str"] == "嵐" and st["port"] is None:
        stop.append("嵐")
        z = sea.zone(x, y)
        say("  嵐が来た")
        r = check(st["captain"].get("胆", 0) + st["captain"].get("航海", 0) + officer_bonus(st, "航海士"), 9, "嵐を乗り切る（胆＋航海）")
        if st.get("storm_left", 0) == 0 and random.random() < 0.15 + 0.12 * z["storm"]:
            st["storm_left"] = random.randint(1, 2)
            say("  [GM] 嵐はまだ続く")
        dmg = sum(roll(2)) + max(0, z["storm"] - 1) * 2
        if st["ship"]["type"] == "小型船":
            dmg += 3
        if r in ("会心",):
            dmg = 0
        elif r == "成功":
            dmg = dmg // 2
        elif r == "大失敗":
            dmg += 6
            st["ship"]["mast_broken"] = True
            lost = random.randint(1, 4)
            st["crew"] -= lost
            say(f"  帆柱が折れた。{lost} 人が波にさらわれた")
        elif r == "失敗":
            if random.random() < 0.5:
                lost = random.randint(1, 3)
                st["crew"] -= lost
                say(f"  {lost} 人が波にさらわれた")
        st["ship"]["hull"] -= dmg
        st["morale"] -= 5
        say(f"  船体 −{dmg}（{st['ship']['hull']}/{spec['hull']}）。士気 −5")
        # 流される
        d = random.randrange(8)
        nx, ny = x + DIRS[d][1], y + DIRS[d][2]
        if sea.sea(nx, ny):
            st["pos"] = [nx, ny]
            say(f"  {DIRS[d][0]}へ流された（{nx},{ny}）")
    if st["port"] is None:
        stop += daily_needs(st, sea, *st["pos"], wind)
    else:
        port_day(st)
    # 出会い
    if st["port"] is None:
        e = encounter(sea, st, *st["pos"])
        if e:
            say(f"  ◆ 出会い：{e}")
            say(f"[GM] gm/出会い表.md の「{e}」を、海域「{sea.zone(*st['pos'])['name']}」で読む")
            if e == "鳥と雲":
                h = land_hint(sea, *st["pos"])
                if h:
                    say(f"[GM] いちばん近い陸：{h[0]}へ {h[1]} マス")
            stop.append("出会い")
    # 船が沈む
    if st["ship"]["hull"] <= 0:
        say("  ！！ 船体が尽きた。船が沈む（ルール.md「沈む」）")
        stop.append("沈没")
    elif st["ship"]["hull"] <= spec["hull"] * 0.25:
        say("  船体が危ない（四分の一を切った）")
    # 船大工
    if st["port"] is None and wind["str"] in ("凪", "弱", "並") and st["ship"]["hull"] < spec["hull"] * 0.7:
        if st["cargo"].get("木材", 0) > 0 and random.random() < 0.5:
            st["ship"]["hull"] += 1
            st["cargo"]["木材"] -= 1
            if st["cargo"]["木材"] == 0:
                del st["cargo"]["木材"]
    # 少ない
    for k in ("water", "food"):
        days = st[k] / max(1, st["crew"] / 30)
        if 0 < days <= 5 and "少ない" not in stop and st["port"] is None:
            say(f"  {'水' if k == 'water' else '食料'}が残り {days:.0f} 日ぶん")
            stop.append("少ない")
    tr = st.setdefault("track", [])
    if not tr or tr[-1] != st["pos"]:
        tr.append(list(st["pos"]))
    officer_casualty(st, crew_before)
    # 人：航海の 5 日ごとの仕掛けと甲板、月末の舞台裏
    if st["port"] is None and st["days_at_sea"] > 0 and st["days_at_sea"] % 5 == 0:
        acted = initiative_round(on_ship(), "船の上")
        ev = deck_event() if random.random() < 0.6 else None
        if acted or ev:
            say("  （船の上で、何かが起きている）")
            stop.append("船の上")
    if st["date"]["d"] == 30:
        backstage(st)
    tick_clocks(st)
    tick_market(1)
    return stop


def dir_to(a, b):
    dx = (b[0] > a[0]) - (b[0] < a[0])
    dy = (b[1] > a[1]) - (b[1] < a[1])
    for i, (_, x, y) in enumerate(DIRS):
        if x == dx and y == dy:
            return i
    return 0


def route(sea, st, goal):
    known = set(map(tuple, st["known"]))
    start = tuple(st["pos"])
    goal = tuple(goal)
    q = deque([start])
    prev = {start: None}
    while q:
        c = q.popleft()
        if c == goal:
            break
        for _, dx, dy in DIRS:
            n = (c[0] + dx, c[1] + dy)
            if n in prev or n not in known or not sea.sea(*n):
                continue
            if sea.cell(*n) == ":" and n != goal:
                continue
            prev[n] = c
            q.append(n)
    if goal not in prev:
        return None
    path = []
    c = goal
    while c != start:
        path.append(list(c))
        c = prev[c]
    return path[::-1]


# ---------------------------------------------------------------- 港
def tick_market(days):
    mk = load(MARKET, {})
    if not mk:
        return
    for pname, goods in mk.items():
        for g, v in goods.items():
            for key in ("stock", "glut"):
                if key in v:
                    norm = v.get("norm", 0) if key == "stock" else 0
                    v[key] += (norm - v[key]) * (1 - 0.92 ** days)
    save(MARKET, mk)


def init_market():
    pd = load(PORTS)
    mk = {}
    for pname, p in pd["ports"].items():
        mk[pname] = {}
        for g in pd["goods"]:
            e = {"glut": 0.0}
            if g in p["sells"]:
                e["norm"] = p["size"]
                e["stock"] = float(p["size"])
            mk[pname][g] = e
    save(MARKET, mk)


def prices(pname):
    pd = load(PORTS)
    mk = load(MARKET)
    p = pd["ports"][pname]
    rows = []
    for g, (base, kind) in pd["goods"].items():
        e = mk[pname][g]
        tax = 1 + p["tax"]
        buy = None
        if g in p["sells"]:
            ratio = e["stock"] / e["norm"] if e["norm"] else 0
            buy = base * p["sells"][g] * (1 + 0.6 * (1 - ratio)) * tax
            if e["stock"] < 1:
                buy = None
        want = p["wants"].get(g, 0.8 if g not in p["sells"] else p["sells"][g] * 0.85)
        sell = base * want * max(0.3, 1 - 0.5 * e["glut"] / max(10, p["size"])) / tax
        rows.append((g, buy, sell, e.get("stock")))
    return rows


def port_day(st):
    st["wages_due"] += st["crew"] * 0.1
    st["days_unpaid"] += 1
    st["morale"] = min(100, st["morale"] + 2)


def adjacent_port(sea, st):
    x, y = st["pos"]
    for _, dx, dy in DIRS:
        p = sea.port_at.get((x + dx, y + dy))
        if p and p["name"] in st["ports_known"]:
            return p
    return None


# ---------------------------------------------------------------- 人
def npcs():
    return load(NPCF, {"people": {}, "relations": [], "crew_mood": {}})


def initiative_round(names, label):
    """仕掛け手番。2d6＋能動 ≧ 10 で仕掛ける。仕掛けた者の名を返す。"""
    nd = npcs()
    acted = []
    for n in names:
        pp = nd["people"][n]
        a, b = roll()
        t = a + b + pp["能動"]
        mark = "仕掛ける" if t >= 10 else "様子を見る"
        say(f"[GM] 仕掛け〔{label}〕{n}：2d6[{a},{b}]+能動{pp['能動']} = {t} / 10 → {mark}")
        if t >= 10:
            acted.append(n)
    if acted:
        say(f"[GM] → {'・'.join(acted)} が帳面の未着手から一つ実行する（gm/NPCの動かし方.md 三）")
    return acted


def on_ship():
    return [n for n, p in npcs()["people"].items() if p["alive"] and p["where"] == "船"]


def deck_event():
    nd = npcs()
    ship = on_ship()
    if len(ship) < 2:
        return None
    rel = {(a, b): v for a, b, v in nd["relations"]}
    pairs = []
    for i, x in enumerate(ship):
        for y in ship[i + 1:]:
            v1, v2 = rel.get((x, y), 0), rel.get((y, x), 0)
            pairs.append((x, y, v1, v2, abs(v1) + abs(v2) + 10))
    tot = sum(p[4] for p in pairs)
    r = random.uniform(0, tot)
    for x, y, v1, v2, w in pairs:
        r -= w
        if r <= 0:
            break
    kind = "ぶつかる" if (v1 + v2) / 2 < 0 else "結びつく"
    k = random.randint(1, 6)
    say(f"[GM] 甲板の出来事：{x} と {y}（思い {v1:+d}／{v2:+d}）→「{kind}」の {k}（gm/NPCの動かし方.md 四）")
    return (x, y, kind, k)


def backstage(st):
    names = [n for n, p in npcs()["people"].items() if p["alive"] and p["where"] != "船"]
    acted = initiative_round(names, "舞台裏")
    if acted:
        say("[GM] 舞台裏で動いた者は、何をしたかを一行決めて帳面に書く（主人公は知らない）")


def officer_casualty(st, before):
    lost = before - st["crew"]
    if lost <= 0 or before <= 0:
        return
    for n in on_ship():
        if random.random() < min(1.0, lost / before):
            say(f"[GM] 士官が巻きこまれたかも：{n}。dice.py fate <体> 1 を振る（gm/NPCの動かし方.md 八）")


# ---------------------------------------------------------------- 時計
def tick_clocks(st):
    cl = load(CLOCKS, {})
    changed = False
    for name, c in cl.items():
        if name.startswith("_") or c.get("done"):
            continue
        if random.random() < c["chance"]:
            c["value"] += 1
            changed = True
            if c["value"] >= c["max"]:
                c["done"] = True
                c["done_date"] = date_str(st)
                say(f"[GM] 時計が満ちた：{name}（gm/時計.md を読んで起こす）")
    if changed:
        save(CLOCKS, cl)


# ---------------------------------------------------------------- 書き出し
def render(sea, st, gm=False):
    known = set(map(tuple, st["known"]))
    lines = []
    lines.append("     " + "".join(str(x // 10) if x % 10 == 0 else " " for x in range(sea.w)))
    lines.append("     " + "".join(str(x % 10) for x in range(sea.w)))
    portchars = {}
    for p in sea.ports:
        if gm or p["name"] in st["ports_known"]:
            portchars[(p["x"], p["y"])] = "P"
    findchars = {}
    for f in sea.finds:
        if gm or f["name"] in st["found"]:
            findchars[(f["x"], f["y"])] = "*"
    for y in range(sea.h):
        row = []
        for x in range(sea.w):
            if [x, y] == st["pos"]:
                row.append("@")
            elif not gm and (x, y) not in known:
                row.append(" ")
            elif (x, y) in portchars:
                row.append("P")
            elif (x, y) in findchars:
                row.append("*")
            else:
                c = sea.cell(x, y)
                row.append({"~": "~", ".": "~", ":": ":", "m": "m", "#": "#"}[c] if not gm else c)
        lines.append(f"{y:3d}  " + "".join(row))
    return lines


def write_public(sea, st):
    lines = render(sea, st)
    ports = [p for p in sea.ports if p["name"] in st["ports_known"]]
    md = ["# 海図（瀬島の）", "", f"{date_str(st)} の時点。見たところ・聞いて描きこんだところだけ。",
          "", "`@` いまの船　`#` 陸　`~` 海　`:` 浅瀬・暗礁　`m` 藻の浮く海　`P` 港　`*` 見つけたもの　空白はまだ誰も描いていない海",
          "", "上が北。一マスは、よい風でほぼ半日〜一日の道のり。", "", "```", *lines, "```", "", "## 港", "",
          "| 港 | 位置 | 国・人々 |", "|---|---|---|"]
    for p in ports:
        md.append(f"| {p['name']} | ({p['x']},{p['y']}) | {p['nation']} |")
    md += ["", "## 見つけたもの", "", "| 名 | 位置 | 見つけた日 | 地理院に報告 |", "|---|---|---|---|"]
    for f in sea.finds:
        if f["name"] in st["found"]:
            info = st["found"][f["name"]]
            md.append(f"| {f['name']} | ({f['x']},{f['y']}) | {info['date']} | {'済' if info['reported'] else 'まだ'} |")
    PUBMAP.parent.mkdir(exist_ok=True)
    PUBMAP.write_text("\n".join(md) + "\n", encoding="utf-8")
    say(f"書き出した：{PUBMAP.relative_to(ROOT)}")


def write_svg(sea, st):
    """瀬島の海図を絵にする。道具を動かすたびに書き直す（見えたところだけ）。"""
    C = 12
    top = 44
    W, H = sea.w * C, sea.h * C + top + 30
    known = set(map(tuple, st["known"]))
    col = {"~": "#2f6f9f", ".": "#4a8fbf", ":": "#7fb6d6", "m": "#5f8f5a", "#": "#d8c89a"}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="Yu Gothic, Meiryo, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#1b1f24"/>']
    # 見出し
    days = max(1, st["crew"]) / 30
    wind = st.get("wind")
    head = (f"{date_str(st)}　{st['ship']['name']}　" + (f"{st['port']} の港" if st["port"] else f"({st['pos'][0]},{st['pos'][1]})")
            + f"　水 {st['water'] / days:.0f}日・食料 {st['food'] / days:.0f}日　士気 {st['morale']}　船体 {st['ship']['hull']}/{ship_spec(st)['hull']}"
            + (f"　{wind_str(wind)}" if wind and not st["port"] else ""))
    o.append(f'<text x="10" y="28" font-size="18" fill="#f2e6c8">{head}</text>')
    o.append(f'<g transform="translate(0,{top})">')
    # 霧（まだ描いていない海）
    o.append(f'<rect width="{sea.w * C}" height="{sea.h * C}" fill="#2a2e33"/>')
    for (x, y) in known:
        c = sea.cell(x, y)
        o.append(f'<rect x="{x * C}" y="{y * C}" width="{C}" height="{C}" fill="{col.get(c, "#2f6f9f")}"/>')
        if c == ":":
            o.append(f'<circle cx="{x * C + 6}" cy="{y * C + 6}" r="1.6" fill="#e8f4fa"/>')
    # 目盛り
    for x in range(0, sea.w, 10):
        o.append(f'<line x1="{x * C}" y1="0" x2="{x * C}" y2="{sea.h * C}" stroke="#ffffff" stroke-opacity="0.08"/>')
        o.append(f'<text x="{x * C + 2}" y="{sea.h * C + 16}" font-size="11" fill="#9aa3ad">{x}</text>')
    for y in range(0, sea.h, 10):
        o.append(f'<line x1="0" y1="{y * C}" x2="{sea.w * C}" y2="{y * C}" stroke="#ffffff" stroke-opacity="0.08"/>')
        o.append(f'<text x="2" y="{y * C + 11}" font-size="11" fill="#9aa3ad">{y}</text>')
    # 航跡
    tr = st.get("track", [])
    if len(tr) > 1:
        pts = " ".join(f"{x * C + 6},{y * C + 6}" for x, y in tr)
        o.append(f'<polyline points="{pts}" fill="none" stroke="#ffd166" stroke-width="2" stroke-dasharray="4 3" stroke-opacity="0.85"/>')
    # 発見
    for f in sea.finds:
        if f["name"] in st["found"]:
            x, y = f["x"] * C + 6, f["y"] * C + 6
            o.append(f'<text x="{x}" y="{y + 5}" font-size="14" text-anchor="middle" fill="#ffe680">★</text>')
            o.append(f'<text x="{x + 8}" y="{y + 16}" font-size="10" fill="#ffe680">{f["name"]}</text>')
    # 港
    for p in sea.ports:
        if p["name"] in st["ports_known"]:
            x, y = p["x"] * C + 6, p["y"] * C + 6
            visited = p["name"] in st["visited"]
            o.append(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{"#e63946" if visited else "#1b1f24"}" stroke="#e63946" stroke-width="2"/>')
            o.append(f'<text x="{x + 7}" y="{y - 5}" font-size="12" fill="#ffffff" stroke="#1b1f24" stroke-width="3" paint-order="stroke">{p["name"]}</text>')
    # 船
    x, y = st["pos"][0] * C + 6, st["pos"][1] * C + 6
    o.append(f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="#ffd166" stroke-width="2"/>')
    o.append(f'<path d="M{x - 5},{y + 2} L{x + 5},{y + 2} L{x + 3},{y + 5} L{x - 3},{y + 5} Z M{x},{y + 2} L{x},{y - 6} L{x + 4},{y} Z" fill="#ffd166"/>')
    o.append('</g>')
    o.append(f'<text x="10" y="{H - 8}" font-size="11" fill="#9aa3ad">灰色＝まだ誰も描いていない海　赤丸＝港（塗りは入ったことのある港）　★＝見つけたもの　点線＝この船の航跡</text>')
    o.append('</svg>')
    PUBSVG.parent.mkdir(exist_ok=True)
    PUBSVG.write_text("\n".join(o), encoding="utf-8")


def show_status(sea, st):
    spec = ship_spec(st)
    sh = st["ship"]
    x, y = st["pos"]
    where = f"{st['port']} の港" if st["port"] else f"({x},{y}) {sea.zone(x, y)['name']}"
    say(f"{date_str(st)}　{where}")
    say(f"船：{sh['name']}（{sh['type']}）船体 {sh['hull']}/{spec['hull']}　砲 {sh.get('guns', spec['guns'])}"
        + ("　帆柱が折れている" if sh.get("mast_broken") else ""))
    say(f"水夫 {st['crew']} 人（定員 {spec['crew']}・最低 {spec['min']}）　士気 {st['morale']}　病人 {st.get('sick', 0)}")
    days = st["crew"] / 30 if st["crew"] else 1
    say(f"水 {st['water']:.0f} 樽（{st['water'] / days:.0f} 日）　食料 {st['food']:.0f} 樽（{st['food'] / days:.0f} 日）"
        f"　積荷 {cargo_used(st)}/{spec['hold']}")
    if st["cargo"]:
        say("積荷：" + "、".join(f"{k} {v}" for k, v in st["cargo"].items()))
    say(f"金貨 {st['gold']}　たまった給金 {st['wages_due']:.0f}（{st['days_unpaid']} 日ぶん）　借金 {st.get('debt', 0)}")
    say(f"航海 {st['days_at_sea']} 日目　新しい食べ物から {st['days_no_fresh']} 日")


# ---------------------------------------------------------------- 本体
def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    sea = Sea()
    if cmd == "init":
        if STATE.exists() and "--force" not in args:
            sys.exit("状態.json はもうある（作り直すなら --force）")
        save(STATE, new_state(sea))
        init_market()
        print("状態.json と gm/相場.json を作った")
        return
    st = load(STATE)
    try:
        run(cmd, args[1:], sea, st)
    finally:
        save(STATE, st)
        try:
            write_svg(sea, st)
        except Exception as e:  # 絵が描けなくても遊びは止めない
            print(f"（海図の絵が書けなかった：{e}）")
        flush_log(args)


def new_state(sea):
    """遊び始めの状態。主人公を作ったあと、名前と能力を書きこむ。"""
    known = []
    for y in range(sea.h):
        for x in range(sea.w):
            if x >= 45 and y <= 19:
                known.append([x, y])
    rl = next(p for p in sea.ports if p["name"] == "リアナ")
    pos = None
    for _, dx, dy in DIRS:
        if sea.sea(rl["x"] + dx, rl["y"] + dy):
            pos = [rl["x"] + dx, rl["y"] + dy]
            break
    return {
        "date": {"y": 1472, "m": 3, "d": 1},
        "pos": pos, "port": "リアナ",
        "captain": {"名": "（未定）", "体": 0, "才": 0, "胆": 0, "弁": 0, "目": 0,
                    "航海": 0, "交易": 0, "指揮": 0, "砲術": 0, "白兵": 0, "学識": 0, "交渉": 0},
        "ship": {"name": "（未定）", "type": "キャラベル", "hull": 50},
        "crew": 24, "officers": [
            {"name": "ベニト・カルヴォ", "role": "航海士", "bonus": 1},
            {"name": "イネス・ソラ", "role": "主計長", "bonus": 0},
            {"name": "グスマン", "role": "水夫長", "bonus": 1},
            {"name": "ルカ", "role": "見習い・通詞", "bonus": 0}], "morale": 65, "sick": 0,
        "water": 20, "food": 20, "cargo": {},
        "gold": 600, "debt": 1500, "wages_due": 0, "days_unpaid": 0,
        "days_at_sea": 0, "days_no_fresh": 0,
        "fame": {"商": 0, "探": 0, "武": 0},
        "known": known, "ports_known": [p["name"] for p in sea.ports if p["known"]],
        "visited": ["リアナ"], "found": {}, "generation": 1,
    }


def run(cmd, a, sea, st):
    pd = load(PORTS)
    if cmd == "status":
        show_status(sea, st)
    elif cmd == "look":
        x, y = st["pos"]
        say(f"({x},{y}) {sea.zone(x, y)['name']}　{wind_str(st.get('wind', {'dir': 0, 'str': '凪'}))}")
        for n in reveal(sea, st, x, y, 2):
            say("  " + n)
        known = set(map(tuple, st["known"]))
        for yy in range(y - 3, y + 4):
            say("  " + "".join("@" if [xx, yy] == st["pos"] else (sea.cell(xx, yy).replace(".", "~") if (xx, yy) in known else " ")
                               for xx in range(x - 5, x + 6)))
    elif cmd in ("sail", "goto", "wait"):
        if st["port"] and cmd != "wait":
            sys.exit("港の中。先に leave")
        if cmd == "sail":
            heading = ALIAS.get(a[0])
            if heading is None:
                sys.exit("方角がわからない")
            days = int(a[1]) if len(a) > 1 else 1
            path = None
        elif cmd == "goto":
            path = route(sea, st, (int(a[0]), int(a[1])))
            if path is None:
                sys.exit("海図に描いてある海だけでは、そこへ行けない")
            say(f"道のり {len(path)} マス")
            heading = None
            days = int(a[2]) if len(a) > 2 else 60
        else:
            heading, path = None, None
            days = int(a[0]) if a else 1
        for i in range(days):
            stop = one_day(sea, st, heading, path)
            if stop and cmd != "wait":
                say(f"→ 止まる：{'・'.join(dict.fromkeys(stop))}")
                break
            if stop and cmd == "wait" and set(stop) - {"少ない"}:
                say(f"→ 止まる：{'・'.join(dict.fromkeys(stop))}")
                break
            if path is not None and not path:
                break
        show_status(sea, st)
    elif cmd == "land":
        x, y = st["pos"]
        shore = [(x + dx, y + dy) for _, dx, dy in DIRS if sea.cell(x + dx, y + dy) == "#"]
        if not shore:
            sys.exit("隣に陸がない")
        dry = 43 <= x <= 49 and 17 <= y <= 27
        r = check(st["captain"].get("目", 0) + st["captain"].get("才", 0), 9 if dry else 7, "水場と食べ物を探す（目＋才）")
        if r in ("成功", "会心", "紙一重"):
            cap = ship_spec(st)["hold"] - cargo_used(st)
            w = min(cap, random.randint(10, 30) if r != "紙一重" else random.randint(4, 10))
            st["water"] += w
            st["days_no_fresh"] = 0
            st["morale"] = min(100, st["morale"] + 5)
            st["sick"] = max(0, st.get("sick", 0) - 2)
            say(f"  水を {w} 樽くんだ。果物と獣の肉。士気 +5、壊血病の数えなおし")
        advance_date(st)
        say(f"【{date_str(st)}】上陸に一日")
        say("[GM] 上陸の出来事：gm/出会い表.md の「上陸」を振る。調べられる発見物は下")
        for f in sea.finds:
            if f["how"] == "land" and (f["x"], f["y"]) in shore and f["name"] not in st["found"]:
                say(f"[GM] 調べれば見つかる：{f['name']}（学識か目で 目標 8）")
        for k in ("water", "food"):
            st[k] = max(0, st[k] - st["crew"] / 30)
        tick_clocks(st)
    elif cmd == "enter":
        p = adjacent_port(sea, st)
        if not p:
            sys.exit("隣に知っている港がない")
        st["port"] = p["name"]
        st["days_at_sea"] = 0
        st["days_no_fresh"] = 0
        st["morale"] = min(100, st["morale"] + 10)
        st["sick"] = 0
        if p["name"] not in st["visited"]:
            st["visited"].append(p["name"])
            say(f"★ はじめての港：{p['name']}（{p['nation']}）")
            say(f"[GM] gm/港.md の「{p['name']}」を読む")
        say(f"{p['name']} に入った。士気 +10")
        here = [n for n, q in npcs()["people"].items() if q["alive"] and q["where"] == p["name"]]
        initiative_round(on_ship() + here, f"入港・{p['name']}")
        if p["name"] in pd["ports"]:
            show_market(p["name"])
    elif cmd == "market":
        need_port(st)
        show_market(st["port"])
    elif cmd in ("buy", "sell"):
        need_port(st)
        trade(st, cmd, a[0], int(a[1]))
    elif cmd == "supply":
        need_port(st)
        kind, n = a[0], int(a[1])
        p = pd["ports"][st["port"]]
        unit = (pd["water"] if kind == "水" else pd["food"]) * p["supply"]
        cost = math.ceil(unit * n)
        if cargo_used(st) + n > ship_spec(st)["hold"]:
            sys.exit("船倉に入らない")
        if cost > st["gold"]:
            sys.exit(f"金貨が足りない（{cost} いる）")
        st["gold"] -= cost
        st["water" if kind == "水" else "food"] += n
        say(f"{kind} {n} 樽を積んだ。−{cost} 金貨（残り {st['gold']}）")
    elif cmd == "hire":
        need_port(st)
        n = int(a[0])
        if st["crew"] + n > ship_spec(st)["crew"]:
            sys.exit("定員をこえる")
        cost = n * 5
        st["gold"] -= cost
        st["crew"] += n
        say(f"{n} 人を雇った。支度金 −{cost}（残り {st['gold']}）。水夫 {st['crew']}")
        say("[GM] 雇える人数は港の大きさと名声しだい（ルール.md「水夫を雇う」）。多すぎたら set で戻す")
    elif cmd == "fire":
        n = int(a[0])
        st["crew"] -= n
        say(f"{n} 人に暇を出した。水夫 {st['crew']}")
    elif cmd == "pay":
        need_port(st)
        due = math.ceil(st["wages_due"])
        if due > st["gold"]:
            sys.exit(f"金貨が足りない（{due} いる）")
        st["gold"] -= due
        st["wages_due"] = 0
        st["days_unpaid"] = 0
        st["morale"] = min(100, st["morale"] + 5)
        say(f"給金 {due} を払った。士気 +5（残り {st['gold']}）")
    elif cmd == "repair":
        need_port(st)
        spec = ship_spec(st)
        miss = spec["hull"] - st["ship"]["hull"]
        n = min(miss, int(a[0])) if a else miss
        cost = n * pd["repair_per_point"]
        if st["ship"].get("mast_broken"):
            cost += 150
        if cost > st["gold"]:
            sys.exit(f"金貨が足りない（{cost} いる）")
        st["gold"] -= cost
        st["ship"]["hull"] += n
        st["ship"]["mast_broken"] = False
        days = max(1, n // 10)
        for _ in range(days):
            advance_date(st)
            port_day(st)
        say(f"船体を {n} 直した（{st['ship']['hull']}/{spec['hull']}）。−{cost} 金貨、{days} 日")
    elif cmd == "leave":
        need_port(st)
        say(f"{st['port']} を出た")
        st["port"] = None
    elif cmd == "map":
        write_public(sea, st)
    elif cmd == "gmmap":
        for l in render(sea, st, gm=True):
            print(l)
    elif cmd == "clocks":
        for n, c in load(CLOCKS, {}).items():
            if n.startswith("_"):
                print(f"{n}：{'、'.join(c.get('names', [])) or 'なし'}")
                continue
            print(f"{n}：{c['value']}/{c['max']}（一日 {c['chance']:.0%}）{' 満ちた ' + c.get('done_date', '') if c.get('done') else ''}")
    elif cmd == "set":
        k, v = a[0], a[1]
        keymap = {"士気": "morale", "水夫": "crew", "金貨": "gold", "水": "water", "食料": "food", "借金": "debt"}
        if k == "船体":
            st["ship"]["hull"] = int(v)
        elif k in keymap:
            st[keymap[k]] = type(st[keymap[k]])(float(v))
        elif k.startswith("積荷:"):
            g = k.split(":", 1)[1]
            if int(v) <= 0:
                st["cargo"].pop(g, None)
            else:
                st["cargo"][g] = int(v)
        else:
            sys.exit("その値は set できない")
        say(f"set {k} = {v}")
    elif cmd == "npc":
        nd = npcs()
        name = a[0]
        if name not in nd["people"]:
            sys.exit("その名の人物は gm/NPC.json にいない（足すなら、遊ぶ前か、場面に三度出てから）")
        pp = nd["people"][name]
        if a[1] == "dead":
            pp["alive"] = False
            for o in st.get("officers", []):
                if o["name"].startswith(name.split("・")[0]):
                    o["alive"] = False
        elif a[1] == "where":
            pp["where"] = a[2]
        elif a[1] in ("能動", "押し"):
            pp[a[1]] = int(a[2])
        save(NPCF, nd)
        say(f"[GM] {name}：{pp}")
    elif cmd == "rel":
        nd = npcs()
        x, y, dv = a[0], a[1], int(a[2])
        for r in nd["relations"]:
            if r[0] == x and r[1] == y:
                r[2] = max(-50, min(50, r[2] + dv))
                break
        else:
            nd["relations"].append([x, y, max(-50, min(50, dv))])
        save(NPCF, nd)
        say(f"[GM] {x} → {y} の思い {dv:+d}")
    elif cmd == "who":
        nd = npcs()
        for n, q in nd["people"].items():
            print(f"{n}：{'生' if q['alive'] else '死'}・{q['where']}・能動{q['能動']}・押し{q['押し']}")
        for x, y, v in nd["relations"]:
            print(f"  {x} → {y}：{v:+d}")
    elif cmd == "find":
        name = a[0]
        if not any(f["name"] == name for f in sea.finds):
            sys.exit("その名の発見物はない")
        st["found"][name] = {"date": date_str(st), "reported": False}
        st["morale"] = min(100, st["morale"] + 5)
        say(f"★ 発見：{name}")
    elif cmd == "report":
        if st["port"] != "リアナ":
            sys.exit("報告はリアナの地理院で")
        vals = {f["name"]: f["value"] for f in sea.finds}
        firsts = load(CLOCKS, {}).get("_先に報告された", {}).get("names", [])
        total_g, total_f = 0, 0
        for n, info in st["found"].items():
            if info["reported"]:
                continue
            v = vals[n]
            if n in firsts:
                v = max(1, v // 3)
                say(f"  {n}：すでに他の者が報告していた。値は三分の一")
            g, f = v * 120, v * 10
            info["reported"] = True
            total_g += g
            total_f += f
            say(f"  {n}：褒美 {g} 金貨、探検の名声 +{f}")
        st["gold"] += total_g
        st["fame"]["探"] += total_f
        say(f"報告した。合わせて {total_g} 金貨、名声（探）+{total_f}")
        say("[GM] 報告の写しがどこへ流れるか：gm/世界の裏.md「地理院の書記」")
    else:
        print(__doc__)


def need_port(st):
    if not st["port"]:
        sys.exit("港にいない")


def show_market(pname):
    rows = prices(pname)
    say(f"── {pname} の相場（一荷あたりの金貨。買値は在庫が減るほど上がり、売値は売りこむほど下がる）")
    for g, buy, sell, stock in rows:
        b = f"{buy:6.0f}" if buy else "     -"
        stk = f"在庫{stock:4.0f}" if stock is not None else ""
        say(f"  {g:　<6} 買 {b}　売 {sell:6.0f}　{stk}")


def trade(st, cmd, g, n):
    pd = load(PORTS)
    mk = load(MARKET)
    p = pd["ports"][st["port"]]
    e = mk[st["port"]][g]
    total = 0
    if cmd == "buy":
        if g not in p["sells"]:
            sys.exit("この港では売っていない")
        if cargo_used(st) + n > ship_spec(st)["hold"]:
            sys.exit("船倉に入らない")
        for _ in range(n):
            pr = [r for r in prices(st["port"]) if r[0] == g][0][1]
            if pr is None:
                say("  在庫が尽きた")
                break
            pr = math.ceil(pr)
            if pr > st["gold"]:
                say("  金貨が尽きた")
                break
            st["gold"] -= pr
            total += pr
            st["cargo"][g] = st["cargo"].get(g, 0) + 1
            e["stock"] -= 1
            save(MARKET, mk)
        say(f"{g} を {st['cargo'].get(g, 0)} 荷に（{total} 金貨払った。残り {st['gold']}）")
    else:
        have = st["cargo"].get(g, 0)
        n = min(n, have)
        for _ in range(n):
            pr = math.floor([r for r in prices(st["port"]) if r[0] == g][0][2])
            st["gold"] += pr
            total += pr
            st["cargo"][g] -= 1
            e["glut"] += 1
            if "stock" in e:
                e["stock"] += 1
            save(MARKET, mk)
        if st["cargo"].get(g) == 0:
            del st["cargo"][g]
        st["fame"]["商"] += total // 500
        say(f"{g} を {n} 荷売った。+{total} 金貨（残り {st['gold']}）。名声（商）+{total // 500}")


if __name__ == "__main__":
    main()
