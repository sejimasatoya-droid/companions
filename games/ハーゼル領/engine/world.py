#!/usr/bin/env python3
"""世界シミュレーション（ハーゼル領記）

ハーゼルの外の世界を、季節ごとにダイスで動かす。
- 天候の前線：どこからどこまで凶作・豊作か
- 経済と人口、技術（発明と広まり）、流行
- 君主の老いと死、跡目争い、内乱、国の崩壊と独立
- 戦：宣戦、戦い、地域の奪い合い、講和
- 疫病の広がり、魔獣の災い（町が滅ぶほどのものも）
- 突飛な出来事：異世界からの勇者の召喚、竜の目覚め、星が落ちる、聖人の出現 など
- 語り部（RimWorld の AI ストーリーテラーに倣う）：大きな出来事が続きすぎないよう、また長く途切れないよう、間合いを取る
- 知らせ（Dwarf Fortress に倣う）：世界の出来事は、ハーゼルからの距離に応じて遅れて、噂として届く。遠くの小さな出来事は届かない

使い方:
  python3 engine/world.py init               初期状態を作る（engine/save/world.json）
  python3 engine/world.py status             世界の様子（GM 用）
  python3 engine/world.py tick [N]           N 季節進める（単独で試すとき）
  python3 engine/world.py sim --years 60 --seeds 200   調整用の統計（セーブは変えない）
  python3 engine/world.py chronicle --years 30 --seed 7  試しに年代記を出す（セーブは変えない）
hazel.py の advance からは、季節の初め（芽月・草月・実月・聖月の第1週）に tick(1) が呼ばれる。
"""
import argparse
import copy
import json
import math
import os
import random
import sys
from collections import deque, Counter

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "world.json")
SAVE = os.path.join(BASE, "save", "world.json")
SEASONS = ["春", "夏", "秋", "冬"]

# ---------------------------------------------------------------- 調整用の値（sim で決めた）
P = {
    "front_n": (1, 3),          # 季節ごとの天候の前線の数
    "front_bad": 0.55,          # 前線が悪いもの（日照り・長雨・冷夏）である見こみ
    "war_base": 0.009,          # 隣りあう国どうしが、季節ごとに戦を始める基本の見こみ（関係・野心で増減）
    "peace_base": 0.15,         # 戦が季節ごとに講和に向かう基本の見こみ（疲れで増える）
    "conquer": 0.22,            # 戦いで大きく勝ったとき、地域を奪う見こみ
    "overext": 0.4,             # 地域を奪うたびの安定の低下
    "revolt": 0.025,             # 奪われた地域が、安定の低い国から独立する見こみ（季節ごと）
    "plague_new": 0.0025,        # 地域ごとの、季節ごとの疫病の芽生え
    "plague_spread": 0.18,       # 疫病が隣へ移る見こみ
    "monster_disaster": 0.005,  # 地域ごとの、季節ごとの大きな魔獣の災いの基本（魔獣の値で増える）
    "invent_mult": 1.0,
    "spread": 0.06,             # 技術が隣の国へ広まる見こみ（季節ごと）
    "trend_new": 0.35,          # 季節ごとに、どこかで新しい流行が始まる見こみ
    "odd_base": 0.14,           # 季節ごとの、突飛な出来事の基本の見こみ
    "drama_quiet": 6,           # 大きな出来事が途切れたら、季節いくつで語り部が後押しするか
    "drama_cool": 2,            # 大きな出来事のあと、季節いくつは大きな出来事を抑えるか
    "death_k": 0.002,           # 君主の死の見こみ：年に 0.002×e^(0.075×(年齢−20))（60 歳で年 4%、70 歳で年 9%、80 歳で年 18%）
}

ODD = [
    # (id, 重み, 条件, 説明) 実際の処理は odd_event()
    ("勇者召喚", 2), ("竜の目覚め", 3), ("星が落ちる", 3), ("聖人の出現", 4), ("偽王の出現", 3),
    ("遺跡の発見", 5), ("錬金の金", 2), ("大地震", 2), ("火の山", 2), ("魔の王", 1),
    ("双子の奇跡", 3), ("海の怪物", 3), ("魔石の大鉱脈", 3), ("消えた村", 3), ("刻の止まる夜", 1),
]


def d(n):
    return random.randint(1, n)


def clamp(v, lo=0.0, hi=10.0):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- 状態
_DATA = None


def load_data():
    global _DATA
    if _DATA is None:
        with open(DATA, encoding="utf-8") as f:
            _DATA = json.load(f)
    return _DATA


def init_state(year=818, season=2):
    data = load_data()
    W = {"year": year, "season": season, "t": 0,
         "regions": copy.deepcopy(data["regions"]),
         "polities": copy.deepcopy(data["polities"]),
         "rel": {}, "wars": copy.deepcopy(data["wars"]),
         "tech": {}, "trends": [], "plagues": {}, "heroes": [], "events": [], "news": [],
         "drama": {"since_big": 0}, "home": data["home"], "harvest": {}, "dead": []}
    for k, v in data["relations"].items():
        W["rel"][k] = v
    for pid, p in W["polities"].items():
        p["orig"] = [r for r, rg in W["regions"].items() if rg["owner"] == pid]
        p["alive"] = True
        p["exhaust"] = 0
        W["tech"][pid] = []
    for r, rg in W["regions"].items():
        rg["core"] = rg["owner"]
        rg["base_pop"] = rg["pop"]
    for inv_id, inv in data["inventions"].items():
        if inv.get("origin"):
            own = W["regions"][inv["origin"]]["owner"]
            W["tech"][own].append(inv_id)
            for q in inv.get("also", []):
                W["tech"][q].append(inv_id)
    W["dist"] = bfs(W, W["home"])
    return W


def bfs(W, start):
    dist = {start: 0}
    q = deque([start])
    while q:
        r = q.popleft()
        for n in W["regions"][r]["nb"]:
            if n not in dist:
                dist[n] = dist[r] + 1
                q.append(n)
    return dist


def load():
    if not os.path.exists(SAVE):
        W = init_state()
        save(W)
        return W
    with open(SAVE, encoding="utf-8") as f:
        return json.load(f)


def save(W):
    os.makedirs(os.path.dirname(SAVE), exist_ok=True)
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(W, f, ensure_ascii=False, indent=1)


def rel(W, a, b):
    k = f"{a}|{b}" if f"{a}|{b}" in W["rel"] else f"{b}|{a}"
    return W["rel"].get(k, 0)


def add_rel(W, a, b, dv):
    k = f"{a}|{b}" if f"{a}|{b}" in W["rel"] or f"{b}|{a}" not in W["rel"] else f"{b}|{a}"
    W["rel"][k] = max(-10, min(10, W["rel"].get(k, 0) + dv))


def regions_of(W, pid):
    return [r for r, rg in W["regions"].items() if rg["owner"] == pid]


def fr(W, pid):
    regs = regions_of(W, pid)
    return regs[0] if regs else None


def neighbors_pol(W, pid):
    s = set()
    for r in regions_of(W, pid):
        for n in W["regions"][r]["nb"]:
            o = W["regions"][n]["owner"]
            if o and o != pid:
                s.add(o)
    return s


def pname(W, pid):
    return W["polities"][pid]["name"] if pid in W["polities"] else "どこにも属さない地"


def rname(W, r):
    return W["regions"][r]["name"]


def at_war(W, a, b):
    return any({w["a"], w["b"]} == {a, b} for w in W["wars"])


def when(W):
    return f"聖暦{W['year']}年 {SEASONS[W['season']]}"


# ---------------------------------------------------------------- 出来事と知らせ
def event(W, text, region, mag, kind, gm=None):
    """mag：1 小さい／2 その国の大事／3 周りの国にも響く／4 大陸を揺るがす"""
    e = {"t": W["t"], "when": when(W), "text": text, "region": region, "mag": mag, "kind": kind}
    if gm:
        e["gm"] = gm
    W["events"].append(e)
    if mag >= 3:
        W["drama"]["since_big"] = 0
    dist = W["dist"].get(region, 6) if region else 3
    reach = {0: -1, 1: 1, 2: 3, 3: 6, 4: 99}[mag]
    if dist <= reach:
        delay = 1 + dist * 2 + d(3) - 1          # 週
        twist = dist >= 3 and random.random() < 0.3
        W["news"].append({"due": W["t"] * 12 + delay, "text": text, "mag": mag, "region": region,
                          "dist": dist, "twisted": twist, "kind": kind})


def pop_news(W, now_week_index):
    """届いた知らせを取り出す。now_week_index は世界の季節 t*12 + その季節の何週目か"""
    out, keep = [], []
    for n in W["news"]:
        (out if n["due"] <= now_week_index else keep).append(n)
    W["news"] = keep
    return out


# ---------------------------------------------------------------- 季節の処理
def weather(W):
    """天候の前線。中心の地域から、隣へ 1〜2 歩広がる"""
    score = {r: random.gauss(0, 0.6) for r in W["regions"]}
    fronts = []
    for _ in range(random.randint(*P["front_n"])):
        c = random.choice(list(W["regions"]))
        bad = random.random() < P["front_bad"]
        radius = random.choice([1, 1, 2])
        dist = {c: 0}
        q = deque([c])
        while q:
            r = q.popleft()
            if dist[r] >= radius:
                continue
            for n in W["regions"][r]["nb"]:
                if n not in dist:
                    dist[n] = dist[r] + 1
                    q.append(n)
        kind = random.choice(["日照り", "長雨", "冷たい夏", "いなご"]) if bad else "穏やかな天気"
        for r, dd in dist.items():
            score[r] += (-1.6 if bad else 1.2) / (1 + dd)
        fronts.append((c, kind, list(dist)))
    res = {}
    for r, s in score.items():
        res[r] = "凶作" if s <= -1.0 else ("豊作" if s >= 1.0 else "平年")
    return res, fronts


def describe_range(W, regs):
    names = [rname(W, r) for r in regs]
    if len(names) == 1:
        return names[0]
    return f"{names[0]}から{names[-1]}まで"


def season_tick(W):
    W["t"] += 1
    W["season"] = (W["season"] + 1) % 4
    if W["season"] == 0:
        W["year"] += 1
    W["drama"]["since_big"] += 1
    quiet = W["drama"]["since_big"] >= P["drama_quiet"]
    cool = W["drama"]["since_big"] < P["drama_cool"] and W["t"] > 1
    drama_k = 1.8 if quiet else (0.4 if cool else 1.0)

    # 1 天候（夏に作柄が決まる）
    if SEASONS[W["season"]] == "夏":
        res, fronts = weather(W)
        W["harvest"] = res
        for c, kind, regs in fronts:
            bad = kind != "穏やかな天気"
            hit = [r for r in regs if res[r] == ("凶作" if bad else "豊作")]
            if len(hit) >= 2:
                txt = (f"{describe_range(W, hit)}にかけて、{kind}で凶作になった" if bad
                       else f"{describe_range(W, hit)}にかけて、天気に恵まれて豊作になった")
                event(W, txt, hit[0], 2 if len(hit) < 3 else 3, "作柄")
        for r, h in res.items():
            rg = W["regions"][r]
            o = rg["owner"]
            if o:
                W["polities"][o]["wealth"] = clamp(W["polities"][o]["wealth"] + {"凶作": -0.6, "平年": 0.05, "豊作": 0.4}[h] * rg["pop"] / 6)
                if h == "凶作":
                    W["polities"][o]["stab"] = clamp(W["polities"][o]["stab"] - 0.3)
            rg["pop"] = round(max(0, rg["pop"] * {"凶作": 0.985, "平年": 1.003, "豊作": 1.006}[h]), 3)

    # 2 暮らしの戻り（安定と富は、なにもなければ少しずつ元へ）
    for pid, p in W["polities"].items():
        if not p["alive"]:
            continue
        p["stab"] = clamp(p["stab"] + (5.5 - p["stab"]) * 0.05)
        p["wealth"] = clamp(p["wealth"] + 0.02 * len(W["tech"][pid]) + (0.05 if not any(pid in (w["a"], w["b"]) for w in W["wars"]) else -0.1))
        p["exhaust"] = max(0, p.get("exhaust", 0) - 0.2)
        p["army"] = clamp(p["army"] + (p["wealth"] - p["army"]) * 0.04)
        p["ruler"]["age"] += 0.25

    # 3 疫病
    plague_tick(W)
    # 4 魔獣
    monster_tick(W, drama_k)
    # 5 君主の死と跡目
    ruler_tick(W)
    # 6 戦
    war_tick(W, drama_k)
    # 7 崩壊と独立
    collapse_tick(W)
    # 8 発明と広まり
    tech_tick(W)
    # 9 流行
    trend_tick(W)
    # 10 突飛な出来事
    if random.random() < P["odd_base"] * drama_k:
        odd_event(W)
    # 11 勇者たち
    hero_tick(W)
    # 関係は少しずつ 0 へ
    for k in list(W["rel"]):
        W["rel"][k] = round(W["rel"][k] * 0.98, 2)


def plague_tick(W):
    names = ["灰咳", "赤斑熱", "水腹", "黒い咳"]
    imm = W.setdefault("immune", {})
    for r, rg in W["regions"].items():
        if r in W["plagues"] or imm.get(r, -1) > W["t"]:
            continue
        dens = rg["pop"] / 6
        if random.random() < P["plague_new"] * (0.5 + dens):
            W["plagues"][r] = {"name": random.choice(names), "left": random.randint(2, 5)}
            event(W, f"{rname(W, r)}で、{W['plagues'][r]['name']}がはやりはじめた", r, 2, "疫病")
    for r, pl in list(W["plagues"].items()):
        rg = W["regions"][r]
        loss = random.uniform(0.02, 0.08)
        rg["pop"] = round(rg["pop"] * (1 - loss), 3)
        o = rg["owner"]
        if o:
            W["polities"][o]["stab"] = clamp(W["polities"][o]["stab"] - 0.15)
            W["polities"][o]["wealth"] = clamp(W["polities"][o]["wealth"] - 0.15)
            if "種痘" in W["tech"].get(o, []):
                pl["left"] -= 1
        for n in rg["nb"]:
            if n not in W["plagues"] and imm.get(n, -1) <= W["t"] and random.random() < P["plague_spread"] * (W["regions"][n]["pop"] / 6 + 0.3):
                W["plagues"][n] = {"name": pl["name"], "left": random.randint(2, 4)}
                event(W, f"{pl['name']}が、{rname(W, r)}から{rname(W, n)}へ広がった", n, 2, "疫病")
        pl["left"] -= 1
        if pl["left"] <= 0:
            del W["plagues"][r]
            imm[r] = W["t"] + random.randint(16, 32)
            if loss > 0.05:
                event(W, f"{rname(W, r)}の{pl['name']}がおさまった。人の数は目に見えて減った", r, 1, "疫病")


def monster_tick(W, drama_k):
    beasts = ["黒熊の群れ", "灰狼の大群", "樹蜘蛛の巣", "岩喰いの大蛇", "翼のある魔獣", "人喰いの大鬼", "毒の霧を吐く大蜥蜴"]
    for r, rg in W["regions"].items():
        rg["monster"] = clamp(rg["monster"] + random.gauss(0, 0.15) + (0.05 if rg["owner"] is None else 0) - (0.03 if rg["owner"] and W["polities"][rg["owner"]]["army"] > 6 else 0))
        p = P["monster_disaster"] * (rg["monster"] / 3) ** 2 * drama_k
        if random.random() < p:
            b = random.choice(beasts)
            sev = d(6) + (1 if rg["monster"] >= 6 else 0)
            if sev >= 6:
                town = random.choice(["川辺の町", "峠の町", "市の立つ町", "古い城下町", "修道院の町"])
                rg["pop"] = round(rg["pop"] * 0.9, 3)
                txt = f"{rname(W, r)}の{town}が、{b}に襲われて滅んだ。生き残った者は散り散りになった"
                event(W, txt, r, 3, "魔獣")
                if rg["owner"]:
                    W["polities"][rg["owner"]]["stab"] = clamp(W["polities"][rg["owner"]]["stab"] - 1)
            else:
                event(W, f"{rname(W, r)}で、{b}が村々を荒らしている", r, 1, "魔獣")


def ruler_tick(W):
    for pid, p in list(W["polities"].items()):
        if not p["alive"]:
            continue
        age = p["ruler"]["age"]
        if p.get("story_ruler"):
            continue  # 物語の人物（摂政・王太子・ウルガ）は GM とクロックが決める
        annual = 0.002 * math.exp(0.075 * max(0, age - 20))
        if random.random() < annual / 4:
            old = p["ruler"]["name"]
            r = d(6) + int(p["stab"] / 3)
            heir = new_name(W, pid, old)
            if r <= 2 and len(regions_of(W, pid)) >= 3:
                event(W, f"{pname(W, pid)}の{old}が亡くなった。跡目をめぐって国が二つに割れた", fr(W, pid), 3, "君主",
                      gm="内乱で国が割れる")
                split(W, pid)
            elif r <= 5:
                p["stab"] = clamp(p["stab"] - 2)
                p["ruler"] = {"name": heir + "（若い）", "age": random.randint(14, 30)}
                event(W, f"{pname(W, pid)}の{old}が亡くなった。若い跡継ぎが立ったが、家臣が言うことを聞かない", fr(W, pid), 2, "君主")
            else:
                p["ruler"] = {"name": heir, "age": random.randint(20, 45)}
                event(W, f"{pname(W, pid)}の{old}が亡くなり、{heir}が跡を継いだ", fr(W, pid), 2, "君主")


NAMES = {
    "アルヴェン": ["コンラート", "オットー", "ハインリヒ", "フリードリヒ", "マティルデ", "ギゼラ", "ルートヴィヒ", "アーデルハイト"],
    "カルディア": ["ボレスワフ", "ヴラスタ", "カジミェシュ", "ミロスラフ", "ドブラヴァ", "ヤロミール"],
    "メリディア": ["アウレリオ", "コンスタンツォ", "ヴァレリア", "ルチアーノ", "セヴェリナ", "マッシモ"],
    "北": ["シグルン", "ハーラル", "オーラヴ", "ラグナ", "エイリク", "アストリッド"],
    "草原": ["バヤン", "テムル", "ボルテ", "ジャムカ", "オユン", "カサル"],
    "東": ["ユンファ", "シェンリー", "ハオラン", "メイリン", "ジュンイー"],
    "砂": ["ラシード", "ファリダ", "ハーリド", "ヤスミン", "サーリム"],
    "海": ["エレア", "ナウス", "セリオン", "マリス", "テティア"],
    "教会": ["ルクス", "ベネディクト", "グレゴール", "インノケンティウス", "クレメンス"],
    "都市": ["市参事会"],
}
CULT = {"摂政": "アルヴェン", "王太子": "アルヴェン", "ガルデン": "アルヴェン", "カルディア": "カルディア", "メリディア": "メリディア",
        "イェーリング": "北", "ヴァルク": "北", "ヤスガル": "草原", "トウラン": "東", "ザハラ": "砂", "セルヴィア": "海", "聖座": "教会",
        "アルトハイム": "都市", "同盟": "都市"}
ORD = ["一世", "二世", "三世", "四世", "五世", "六世"]


def new_name(W, pid, old):
    base = pid.split("・")[0]
    c = CULT.get(base, "アルヴェン")
    if c == "都市":
        return "新しい参事会の長"
    n = random.choice(NAMES[c])
    title = {"教会": "大司教長", "草原": "大族長", "東": "天子", "砂": "首長", "海": "巫女王"}.get(c, "")
    if base == "ヴァルク":
        title = "氏族長"
    if base == "メリディア":
        title = "皇帝"
    return f"{title}{n}{random.choice(ORD) if title in ('皇帝', '大司教長', '') else ''}"


def split(W, pid):
    regs = regions_of(W, pid)
    if len(regs) < 2:
        return
    half = regs[len(regs) // 2:]
    nid = f"{pid}・{d(99)}"
    p = W["polities"][pid]
    W["polities"][nid] = {"name": f"{p['name'].split('（')[0]}（分かれた側）", "kind": p["kind"], "ruler": {"name": "跡目を争った弟", "age": random.randint(20, 40)},
                          "stab": 4, "army": p["army"] * 0.5, "wealth": p["wealth"] * 0.5, "amb": 7, "faith": p["faith"], "magic": p["magic"],
                          "orig": half, "alive": True, "exhaust": 0}
    p["army"] *= 0.6
    p["stab"] = clamp(p["stab"] - 2)
    W["tech"][nid] = list(W["tech"][pid])
    for r in half:
        W["regions"][r]["owner"] = nid
    add_rel(W, pid, nid, -10)
    W["wars"].append({"a": pid, "b": nid, "since": W["t"], "goal": "跡目", "score": 0})


def strength(W, pid):
    p = W["polities"][pid]
    s = p["army"] * (0.6 + p["stab"] / 12) * (1 - min(0.5, p.get("exhaust", 0) / 20))
    for h in W["heroes"]:
        if h["side"] == pid and h["alive"]:
            s += h["power"]
    return max(0.3, s)


def war_tick(W, drama_k):
    alive = [pid for pid, p in W["polities"].items() if p["alive"]]
    # 宣戦
    for a in alive:
        for b in neighbors_pol(W, a):
            if a >= b or at_war(W, a, b) or not W["polities"][b]["alive"]:
                continue
            pa, pb = W["polities"][a], W["polities"][b]
            r = rel(W, a, b)
            agg = max(pa["amb"], pb["amb"]) / 7
            weak = abs(strength(W, a) - strength(W, b)) / 10
            p = P["war_base"] * agg * (1 + max(0, -r) / 4) * (1 + weak) * drama_k * (0.3 if r > 3 else 1)
            if pa["kind"] in ("教会", "都市") or pb["kind"] in ("教会", "都市"):
                p *= 0.15
            if random.random() < p:
                atk, dfn = (a, b) if pa["amb"] + random.random() * 3 >= pb["amb"] + random.random() * 3 else (b, a)
                W["wars"].append({"a": atk, "b": dfn, "since": W["t"], "goal": "地", "score": 0})
                add_rel(W, a, b, -4)
                event(W, f"{pname(W, atk)}が、{pname(W, dfn)}に戦を仕掛けた", fr(W, dfn), 3, "戦")
    # 戦い
    for w in list(W["wars"]):
        a, b = w["a"], w["b"]
        if w not in W["wars"] or w.get("story"):
            continue  # 物語の戦（摂政と王太子の内乱など）は、hazel.py のクロックと GM が決める
        if not (W["polities"].get(a, {}).get("alive") and W["polities"].get(b, {}).get("alive")):
            W["wars"].remove(w)
            continue
        sa, sb = strength(W, a) * random.uniform(0.6, 1.4), strength(W, b) * random.uniform(0.6, 1.4) * 1.1  # 守る側に少し利
        ratio = sa / sb
        win, lose = (a, b) if ratio >= 1 else (b, a)
        big = ratio >= 1.6 or ratio <= 1 / 1.6
        for x in (a, b):
            W["polities"][x]["exhaust"] = W["polities"][x].get("exhaust", 0) + 1
            W["polities"][x]["army"] = clamp(W["polities"][x]["army"] - (0.6 if x == lose else 0.25))
            W["polities"][x]["wealth"] = clamp(W["polities"][x]["wealth"] - 0.15)
        w["score"] += (1 if win == a else -1) * (2 if big else 1)
        if big and random.random() < P["conquer"]:
            front = [r for r in regions_of(W, lose) if any(W["regions"][n]["owner"] == win for n in W["regions"][r]["nb"])
                     and not W["regions"][r].get("protected")]
            if not front and any(W["regions"][r].get("protected") for r in regions_of(W, lose)):
                W.setdefault("home_threat", []).append({"t": W["t"], "by": win})
                pr = [r for r in regions_of(W, lose) if W["regions"][r].get("protected")][0]
                event(W, f"{pname(W, win)}の軍が、{pname(W, lose)}を破って、{rname(W, pr)}へ迫る勢いだという", pr, 3, "戦",
                      gm=f"世界の戦が{rname(W, pr)}を脅かしている（物語の地）。奪うかどうかは GM と hazel.py のクロックで決める")
            # 都（もとの国の最初の地）は、戦の点が 4 以上離れていないと落ちない
            capital = W["polities"][lose]["orig"][0] if W["polities"][lose].get("orig") else None
            if capital in front and abs(w["score"]) < 4 and len(front) == 1:
                front = []
            front = [r for r in front if r != capital or abs(w["score"]) >= 4]
            if front:
                r = random.choice(front)
                W["regions"][r]["owner"] = win
                W["polities"][win]["stab"] = clamp(W["polities"][win]["stab"] - P["overext"])
                W["polities"][lose]["stab"] = clamp(W["polities"][lose]["stab"] - 1)
                event(W, f"{pname(W, win)}が、{pname(W, lose)}を大きく破り、{rname(W, r)}を奪った", r, 3, "戦")
                if not regions_of(W, lose):
                    fall(W, lose, win)
            elif big:
                event(W, f"{pname(W, win)}が、{pname(W, lose)}の軍を大きく破った", fr(W, lose), 2, "戦")
        elif big:
            event(W, f"{pname(W, win)}が、{pname(W, lose)}の軍を大きく破った", fr(W, lose), 2, "戦")
        # 講和
        ex = (W["polities"][a]["exhaust"] + W["polities"][b]["exhaust"]) / 2
        if w in W["wars"] and random.random() < P["peace_base"] + ex * 0.03:
            W["wars"].remove(w)
            add_rel(W, a, b, 3)
            lead = a if w["score"] > 0 else b if w["score"] < 0 else None
            txt = (f"{pname(W, a)}と{pname(W, b)}が講和した" + (f"。{pname(W, lead)}が有利な条件を得た" if lead else "。どちらも得るもののない戦だった"))
            event(W, txt, fr(W, b), 2, "戦")


def fall(W, pid, by=None):
    p = W["polities"][pid]
    p["alive"] = False
    W["dead"].append({"pid": pid, "name": p["name"], "when": when(W), "by": by})
    event(W, f"{p['name']}が滅んだ" + (f"。最後の地は{pname(W, by)}のものになった" if by else ""), p["orig"][0] if p["orig"] else None, 4, "滅亡")
    W["wars"] = [w for w in W["wars"] if pid not in (w["a"], w["b"])]


def collapse_tick(W):
    for pid, p in list(W["polities"].items()):
        if not p["alive"]:
            continue
        regs = regions_of(W, pid)
        if not regs:
            fall(W, pid)
            continue
        # 奪った地の独立
        for r in regs:
            rg = W["regions"][r]
            core = rg["core"]
            if core and core != pid and random.random() < P["revolt"] * (1 + (5 - p["stab"]) / 3):
                if W["polities"].get(core, {}).get("alive"):
                    rg["owner"] = core
                    event(W, f"{rname(W, r)}の民が{pname(W, pid)}に背き、{pname(W, core)}のもとへ戻った", r, 2, "独立")
                elif random.random() < 0.3:
                    cp = W["polities"][core]
                    cp["alive"] = True
                    cp["stab"], cp["army"], cp["wealth"] = 4, 2, 2
                    cp["ruler"] = {"name": "旧王家の生き残り", "age": random.randint(18, 50)}
                    rg["owner"] = core
                    event(W, f"{rname(W, r)}で、滅んだ{cp['name']}の生き残りが兵を挙げ、国を立て直した", r, 3, "独立")
                p["stab"] = clamp(p["stab"] - 0.5)
        # 崩壊
        if p["stab"] <= 0.5 and len(regions_of(W, pid)) >= 3 and random.random() < 0.15:
            event(W, f"{p['name']}で大きな反乱が起き、国が乱れに乱れている", fr(W, pid), 3, "反乱", gm="国が割れる")
            split(W, pid)


def tech_tick(W):
    data = load_data()["inventions"]
    for pid, p in list(W["polities"].items()):
        if not p["alive"]:
            continue
        for iid, inv in data.items():
            if iid in W["tech"][pid] or not inv["base"]:
                continue
            if inv.get("need") and inv["need"] not in W["tech"][pid]:
                continue
            if inv.get("need_magic") and p["magic"] < inv["need_magic"]:
                continue
            if inv.get("need_zone") and not any(W["regions"][r]["zone"] == inv["need_zone"] for r in regions_of(W, pid)):
                continue
            if any(iid in W["tech"][q] for q in W["tech"]):
                continue  # もう世界のどこかにあるものは、広まりで得る
            if any(W["regions"][r].get("protected") and r == W["home"] for r in regions_of(W, pid)):
                continue  # ハーゼルのある国の発明は、ライの計画で決まる
            k = inv["base"] * P["invent_mult"] * (0.5 + p["wealth"] / 10 + p["magic"] / 20) * (p["stab"] / 6)
            if random.random() < k:
                W["tech"][pid].append(iid)
                apply_eff(W, pid, inv["eff"])
                r = fr(W, pid)
                event(W, f"{pname(W, pid)}で、{inv['name']}が生まれた。{inv['text']}", r, 3, "発明")
    # 広まり
    for pid, p in W["polities"].items():
        if not p["alive"]:
            continue
        for q in neighbors_pol(W, pid):
            for iid in W["tech"][q]:
                if iid in W["tech"][pid]:
                    continue
                inv = data[iid]
                if inv.get("need") and inv["need"] not in W["tech"][pid]:
                    continue
                k = P["spread"] * (1.5 if not at_war(W, pid, q) else 0.5) * (1 + rel(W, pid, q) / 20)
                if random.random() < k:
                    W["tech"][pid].append(iid)
                    apply_eff(W, pid, inv["eff"])
                    home_owner = W["regions"][W["home"]]["owner"]
                    from_home = load_data()["inventions"][iid].get("origin") == W["home"]
                    if pid == home_owner:
                        event(W, f"{inv['name']}が、{pname(W, q)}から北部にも伝わってきた。{inv['text']}", W["home"], 2, "発明")
                    elif from_home:
                        event(W, f"北のハーゼルから出た{inv['name']}が、{pname(W, pid)}でも作られはじめたという", fr(W, pid), 2, "発明",
                              gm="ハーゼルの品の名にかかわる")
                    else:
                        event(W, f"{inv['name']}が、{pname(W, q)}から{pname(W, pid)}へ伝わった", fr(W, pid), 0, "発明")


def apply_eff(W, pid, eff):
    p = W["polities"][pid]
    for k, v in eff.items():
        if k == "fert":
            for r in regions_of(W, pid):
                W["regions"][r]["fert"] = clamp(W["regions"][r]["fert"] + v)
        else:
            p[k] = clamp(p.get(k, 5) + v)


def trend_tick(W):
    data = load_data()
    for t in list(W["trends"]):
        t["left"] -= 1
        if t["left"] <= 0:
            W["trends"].remove(t)
            continue
        if random.random() < 0.35:
            cur = random.choice(t["where"])
            nb = [n for n in W["regions"][cur]["nb"] if n not in t["where"]
                  and not (t["kind"] in ("服", "髪", "動物") and W["regions"][n]["owner"] and W["polities"][W["regions"][n]["owner"]]["kind"] == "部族")]
            if nb:
                n = random.choice(nb)
                t["where"].append(n)
                if W["dist"].get(n, 9) <= 1:
                    event(W, t["text"].replace(rname(W, t["where"][0]), rname(W, n)) + "（よそから伝わってきた）", n, 1, "流行")
    if random.random() < P["trend_new"]:
        tpl = random.choice(data["trends"])
        r = random.choice([r for r, rg in W["regions"].items() if rg["pop"] > 1.5])
        text = tpl["text"].replace("{r}", rname(W, r)).replace("{n}", random.choice(data["song_names"]))
        W["trends"].append({"text": text, "where": [r], "left": random.randint(3, 10), "kind": tpl["kind"]})
        event(W, text, r, 1 if W["dist"].get(r, 9) > 1 else 2, "流行")


# ---------------------------------------------------------------- 突飛な出来事と勇者
JP_NAMES = ["タカハシ・ユウト", "サトウ・ミサキ", "スズキ・レン", "ナカムラ・アオイ", "コバヤシ・ハルト", "ヤマダ・ヒナ", "イトウ・ソウタ", "ワタナベ・ユイ"]
JP_KNOW = ["マヨネーズ", "将棋に似た盤の遊び", "算盤", "石鹸と手洗い", "活版の考え", "火薬の作り方", "種痘", "鉄の鋤", "簿記"]


def odd_event(W):
    kinds = [k for k, w in ODD for _ in range(w)]
    k = random.choice(kinds)
    alive = [pid for pid, p in W["polities"].items() if p["alive"]]
    r = random.choice(list(W["regions"]))
    if k == "勇者召喚":
        cands = [pid for pid in alive if W["polities"][pid]["magic"] >= 6 and (any(pid in (w["a"], w["b"]) for w in W["wars"]) or W["polities"][pid]["faith"] >= 7)]
        if not cands:
            return
        pid = random.choice(cands)
        name = random.choice(JP_NAMES)
        hero = {"name": name, "side": pid, "power": round(random.uniform(1.5, 4.0), 1), "alive": True, "loyal": random.randint(3, 9),
                "know": random.choice(JP_KNOW), "since": W["t"]}
        W["heroes"].append(hero)
        event(W, f"{pname(W, pid)}が、大がかりな儀式で、異なる世界から『勇者』を呼び出したという。名は{name}。見たこともない服を着た若者だそうだ",
              fr(W, pid), 4, "勇者",
              gm=f"勇者{name}は日本から召喚された（{hero['know']}を知っている）。力 {hero['power']}、忠誠 {hero['loyal']}")
    elif k == "竜の目覚め":
        cand = [x for x, rg in W["regions"].items() if rg["zone"] in ("山", "寒", "荒")]
        r = random.choice(cand)
        W["regions"][r]["monster"] = clamp(W["regions"][r]["monster"] + 3)
        event(W, f"{rname(W, r)}の山の奥で、古い竜が目を覚ましたという。夜空を横切る大きな影を見た者がいる", r, 4, "竜")
    elif k == "星が落ちる":
        event(W, f"{rname(W, r)}の空に、昼のように明るい星が落ちた。落ちた場所には、見たこともない魔石の塊があるという", r, 3, "天変")
        W["regions"][r]["monster"] = clamp(W["regions"][r]["monster"] + 1)
    elif k == "聖人の出現":
        event(W, f"{rname(W, r)}の村で、手をかざすだけで病を癒やす少女が現れ、聖女と呼ばれている。教会が調べに人をやった", r, 2, "聖人")
    elif k == "偽王の出現":
        pid = random.choice(alive)
        if regions_of(W, pid):
            W["polities"][pid]["stab"] = clamp(W["polities"][pid]["stab"] - 1.5)
            event(W, f"{pname(W, pid)}で、『死んだはずの先王の子』を名のる男が現れ、民が集まっている", fr(W, pid), 2, "偽王")
    elif k == "遺跡の発見":
        event(W, f"{rname(W, r)}で、地の底から旧エルデン帝国の回廊が見つかった。学者と盗掘人が押し寄せている", r, 2, "遺跡",
              gm="七つの塔の一つにかかわるかもしれない（灰の書庫が動く）")
    elif k == "錬金の金":
        pid = random.choice(alive)
        if regions_of(W, pid):
            W["polities"][pid]["wealth"] = clamp(W["polities"][pid]["wealth"] - 1)
            event(W, f"{pname(W, pid)}で、錬金術師が鉛を金に変えたと噂になり、金の値が乱れている。……のちに、ただの金めっきだとわかった", fr(W, pid), 2, "珍事")
    elif k == "大地震":
        W["regions"][r]["pop"] = round(W["regions"][r]["pop"] * 0.95, 3)
        if W["regions"][r]["owner"]:
            W["polities"][W["regions"][r]["owner"]]["wealth"] = clamp(W["polities"][W["regions"][r]["owner"]]["wealth"] - 1)
        event(W, f"{rname(W, r)}で大きな地震があり、町の壁と聖堂が崩れた", r, 3, "天変")
    elif k == "火の山":
        cand = [x for x, rg in W["regions"].items() if rg["zone"] in ("山", "寒", "南")]
        r = random.choice(cand)
        event(W, f"{rname(W, r)}の山が火を噴き、灰が空を覆った。遠くの国まで、空が赤く見えるという", r, 4, "天変")
        for x in W["regions"]:
            if W["dist"].get(x, 9) <= 99 and random.random() < 0.3:
                W["regions"][x]["fert"] = clamp(W["regions"][x]["fert"] - 0.3)
    elif k == "魔の王":
        if any(h.get("demon") for h in W["heroes"]):
            return
        hi = [x for x, rg in W["regions"].items() if rg["monster"] >= 5]
        r = "灰の荒野" if (random.random() < 0.6 or not hi) else random.choice(hi)
        W["regions"][r]["monster"] = 10
        W["heroes"].append({"name": "魔の王", "side": None, "power": 6, "alive": True, "loyal": 0, "demon": True, "home": r, "since": W["t"]})
        event(W, f"{rname(W, r)}で、魔獣を従える『魔の王』が現れたという。魔獣の群れが、まるで軍のように動いている", r, 4, "魔王",
              gm="魔の王は旧帝国の塔の封が解けた跡から生まれた（黒の森の塔の封が解ければ、ハーゼルにも同じことが起こりうる）")
    elif k == "双子の奇跡":
        pid = random.choice(alive)
        event(W, f"{pname(W, pid)}の王家に、生まれながらに祝福の光をまとった双子が生まれた", fr(W, pid), 2, "珍事")
    elif k == "海の怪物":
        cand = [x for x, rg in W["regions"].items() if rg["zone"] == "海"]
        r = random.choice(cand)
        event(W, f"{rname(W, r)}の沖に、船を丸ごと呑む大きな海の怪物が現れ、船が出られなくなった", r, 3, "魔獣")
        if W["regions"][r]["owner"]:
            W["polities"][W["regions"][r]["owner"]]["wealth"] = clamp(W["polities"][W["regions"][r]["owner"]]["wealth"] - 1)
    elif k == "魔石の大鉱脈":
        o = W["regions"][r]["owner"]
        if o:
            W["polities"][o]["wealth"] = clamp(W["polities"][o]["wealth"] + 1.5)
            for q in neighbors_pol(W, o):
                add_rel(W, o, q, -2)
            event(W, f"{rname(W, r)}で、魔石の大きな鉱脈が見つかった。隣の国々が目の色を変えている", r, 3, "珍事")
    elif k == "消えた村":
        event(W, f"{rname(W, r)}で、一つの村の者が、ひと晩のうちに一人残らず消えたという。火のついたままの竈が残っていた", r, 2, "怪異")
    elif k == "刻の止まる夜":
        event(W, f"{rname(W, r)}で、ひと晩、川の流れも鐘の音も止まり、朝になると皆が一日ぶんの記憶をなくしていたという", r, 3, "怪異",
              gm="旧帝国の塔の封の一つが揺らいだ（刻の司の封）。灰の書庫が色めき立つ")


def hero_tick(W):
    for h in W["heroes"]:
        if not h["alive"]:
            continue
        if h.get("demon"):
            r = h["home"]
            for n in W["regions"][r]["nb"]:
                W["regions"][n]["monster"] = clamp(W["regions"][n]["monster"] + 0.3)
            # 勇者に討たれることがある
            heroes = [x for x in W["heroes"] if x["alive"] and not x.get("demon")]
            if heroes and random.random() < 0.08:
                x = random.choice(heroes)
                if x["power"] + random.uniform(0, 5) > h["power"] + random.uniform(0, 4):
                    h["alive"] = False
                    W["regions"][r]["monster"] = 6
                    event(W, f"勇者{x['name']}が、{rname(W, r)}で魔の王を討ち果たした", r, 4, "勇者")
                else:
                    x["alive"] = False
                    event(W, f"勇者{x['name']}が、魔の王に挑んで敗れ、帰らなかった", r, 3, "勇者")
            continue
        roll = random.random()
        side = h["side"]
        if side and not W["polities"].get(side, {}).get("alive"):
            h["side"] = None
            event(W, f"国を失った勇者{h['name']}が、ひとりで旅に出たという", None, 2, "勇者")
            continue
        if roll < 0.02:
            h["alive"] = False
            event(W, f"勇者{h['name']}が、戦場で討たれたという", fr(W, side) if side and regions_of(W, side) else None, 3, "勇者")
        elif roll < 0.04 and h["loyal"] <= 4 and side:
            nb = list(neighbors_pol(W, side))
            if nb:
                new = random.choice(nb)
                h["side"] = new
                event(W, f"勇者{h['name']}が、{pname(W, side)}を見かぎって{pname(W, new)}へ走った", fr(W, new), 3, "勇者")
        elif roll < 0.07 and side:
            # 知っている知恵を広める
            event(W, f"{pname(W, side)}の勇者{h['name']}が、『{h['know']}』という見知らぬ知恵を広めているという", fr(W, side), 2, "勇者",
                  gm=f"日本の知識：{h['know']}。ライがこれを聞けば、同じ世界から来た者だと気づくかもしれない")
            W["polities"][side]["wealth"] = clamp(W["polities"][side]["wealth"] + 0.5)
        elif roll < 0.12:
            regs = [r for r in W["regions"] if W["regions"][r]["monster"] >= 6]
            if regs:
                r = random.choice(regs)
                W["regions"][r]["monster"] = clamp(W["regions"][r]["monster"] - 3)
                event(W, f"勇者{h['name']}が、{rname(W, r)}の魔獣の巣を払った", r, 2, "勇者")


# ---------------------------------------------------------------- ハーゼルへの橋渡し
def home_summary(W):
    """ハーゼル（北部）にかかわる世界の値。hazel.py が使う"""
    home = W["home"]
    owner = W["regions"][home]["owner"]
    return {
        "harvest": W["harvest"].get(home),
        "harvest_near": [W["harvest"].get(n) for n in W["regions"][home]["nb"]],
        "owner": owner,
        "wars": [w for w in W["wars"] if owner in (w["a"], w["b"])],
        "plague_near": [r for r in W["plagues"] if W["dist"].get(r, 9) <= 1],
        "plague_home": home in W["plagues"],
    }


def tick(W, n=1):
    out = []
    for _ in range(n):
        start = len(W["events"])
        season_tick(W)
        out.extend(W["events"][start:])
    return out


# ---------------------------------------------------------------- 調整用の統計
def run_sim(years, seed):
    random.seed(seed)
    W = init_state()
    for _ in range(years * 4):
        season_tick(W)
    return W


def stats(years, seeds):
    agg = Counter()
    maxreg, alive_end, news_per_year, big_news, jp, demons, towns, falls, inv, plag_home, war_home = [], [], [], [], 0, 0, [], [], [], [], []
    for s in range(seeds):
        W = run_sim(years, s)
        c = Counter(e["kind"] for e in W["events"])
        agg.update(c)
        owners = Counter(rg["owner"] for rg in W["regions"].values() if rg["owner"])
        maxreg.append(max(owners.values()))
        alive_end.append(sum(1 for p in W["polities"].values() if p["alive"]))
        delivered = [e for e in W["events"] if W["dist"].get(e["region"], 3 if e["region"] is None else 9) <= {0: -1, 1: 1, 2: 3, 3: 6, 4: 99}[e["mag"]]]
        news_per_year.append(len(delivered) / years)
        big_news.append(sum(1 for e in delivered if e["mag"] >= 3) / years)
        jp += sum(1 for h in W["heroes"] if not h.get("demon"))
        demons += sum(1 for h in W["heroes"] if h.get("demon"))
        towns.append(sum(1 for e in W["events"] if "滅んだ。生き残った" in e["text"]))
        falls.append(len(W["dead"]))
        inv.append(sum(1 for e in W["events"] if e["kind"] == "発明" and "生まれた" in e["text"]))
        plag_home.append(sum(1 for e in W["events"] if e["kind"] == "疫病" and e["region"] == "北部" and "はやり" in e["text"] or (e["kind"] == "疫病" and e["region"] == "北部" and "広がった" in e["text"])))
        war_home.append(sum(1 for e in W["events"] if e["kind"] == "戦" and "仕掛けた" in e["text"] and ("王太子" in e["text"] or "北部" in e["text"])))
    n = seeds
    mean = lambda xs: sum(xs) / len(xs)
    print(f"■ {years} 年 × {seeds} 通り")
    print("  出来事の種類（1 通りあたり、年あたり）")
    for k, v in agg.most_common():
        print(f"    {k}: {v / n / years:.2f}")
    print(f"  いちばん大きい国の地域数：平均 {mean(maxreg):.1f}（最大 {max(maxreg)}／全 24）")
    print(f"  終わりに残った国の数：平均 {mean(alive_end):.1f}")
    print(f"  滅んだ国：平均 {mean(falls):.1f}（{years} 年で）")
    print(f"  町が魔獣に滅ぼされた：平均 {mean(towns):.1f}（{years} 年で）")
    print(f"  新しい発明：平均 {mean(inv):.1f}（{years} 年で）")
    print(f"  勇者の召喚：{jp / n:.2f}（{years} 年で）、魔の王：{demons / n:.2f}")
    print(f"  ハーゼルに届く知らせ：年 {mean(news_per_year):.1f} 件（大きなもの 年 {mean(big_news):.1f} 件）")
    print(f"  北部に疫病：{mean(plag_home):.2f}（{years} 年で）")


def chronicle(years, seed, only_news=False):
    random.seed(seed)
    W = init_state()
    for _ in range(years * 4):
        start = len(W["events"])
        season_tick(W)
        for e in W["events"][start:]:
            dist = W["dist"].get(e["region"], 3) if e["region"] else 3
            reach = {0: -1, 1: 1, 2: 3, 3: 6, 4: 99}[e["mag"]]
            if only_news and dist > reach:
                continue
            mark = "★" * (e["mag"] - 1)
            print(f"{e['when']}　{mark}{e['text']}" + (f"　〔GM：{e['gm']}〕" if e.get("gm") else ""))
    print("\n■ 終わりの世界")
    status(W)


def status(W):
    print(f"{when(W)}（季節 {W['t']}）")
    for pid, p in W["polities"].items():
        if not p["alive"]:
            continue
        regs = regions_of(W, pid)
        print(f"  {p['name']}：地域 {len(regs)}　安定 {p['stab']:.1f} 兵 {p['army']:.1f} 富 {p['wealth']:.1f} 君主 {p['ruler']['name']}（{p['ruler']['age']:.0f}）")
    if W["wars"]:
        print("  戦：" + " / ".join(f"{pname(W, w['a'])} 対 {pname(W, w['b'])}" for w in W["wars"]))
    if W["plagues"]:
        print("  疫病：" + " / ".join(f"{rname(W, r)}（{pl['name']}）" for r, pl in W["plagues"].items()))
    hs = [h for h in W["heroes"] if h["alive"]]
    if hs:
        print("  勇者・魔の王：" + " / ".join(f"{h['name']}（{pname(W, h['side']) if h['side'] else '主なし'}）" for h in hs))
    if W["dead"]:
        print("  滅んだ国：" + " / ".join(f"{x['name']}（{x['when']}）" for x in W["dead"]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    sub.add_parser("status")
    s = sub.add_parser("tick"); s.add_argument("n", nargs="?", type=int, default=1)
    s = sub.add_parser("sim"); s.add_argument("--years", type=int, default=60); s.add_argument("--seeds", type=int, default=200)
    s = sub.add_parser("chronicle"); s.add_argument("--years", type=int, default=30); s.add_argument("--seed", type=int, default=1); s.add_argument("--news", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init":
        save(init_state()); print("世界を作り直した")
    elif a.cmd == "status":
        status(load())
    elif a.cmd == "tick":
        W = load()
        for e in tick(W, a.n):
            print(f"{e['when']}　{e['text']}")
        save(W)
    elif a.cmd == "sim":
        stats(a.years, a.seeds)
    elif a.cmd == "chronicle":
        chronicle(a.years, a.seed, a.news)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
