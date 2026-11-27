# -*- coding: utf-8 -*-
"""楔国：列強の思考と世界の進み（GM専用）

1ターン＝1週。列強は「閣議」の週に方針を見直す（ふだんは4週ごと、事件があれば臨時）。
方針は、国の中の派閥ごとの損得（効用）を派閥の重みで足し、首脳の性格で補正し、
ソフトマックスの確率にして乱数で一つ選ぶ。判断の内訳を必ず出すので、判断記録に写す。

使い方（games/楔国/gm で）:
  python 楔国.py 初期化                 状態.json を作り直す（最初の一回だけ）
  python 楔国.py 進める [週数] [--seed N] 世界を進め、閣議があれば方針を決めて書く
  python 楔国.py 返事 国 受諾|拒否        ノルヴァの返事を記す（要求・通牒への）
  python 楔国.py 記す キー 値             例: 記す ノルヴァ.兵力 14 ／ 記す グラウ.関係 -10
  python 楔国.py 見る [国]               いまの状態（GM用。公開してよいのは国勢表の数字だけ）
  python 楔国.py 釣り合い [--n 400]       三つの打ち方で30年を回し、独立が保てる割合を出す
"""
import argparse
import copy
import json
import math
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
STATE = HERE / "状態.json"

POWERS = ["グラウ", "セレス", "ラドミール", "オルネア"]
ACTIONS = ["静観", "浸透", "工作", "要求", "示威", "友好", "通牒", "侵攻"]
RISK = {"静観": 0, "浸透": 0, "工作": .1, "要求": .15, "示威": .35, "友好": 0, "通牒": .7, "侵攻": 1.0}
WEEKS = 52 * 30

# ---------------------------------------------------------------- 派閥の型
# 行動ごとに {特徴: 係数}。"1" は定数。特徴は features() を見よ（だいたい 0〜1）
ARCH = {
    "軍閥": {
        "静観": {"1": 0.0},
        "浸透": {"1": 0.0},
        "工作": {"1": 0.1, "weak": 0.2},
        "要求": {"1": 0.15, "ore": 0.3, "lean_rival": 0.4, "rel": -0.2},
        "示威": {"1": 0.05, "tension": 0.5, "lean_rival": 0.3, "defense": -0.4},
        "友好": {"1": -0.1, "lean": 0.4},
        "通牒": {"1": -0.3, "tension": 0.6, "ore": 0.3, "lean_rival": 0.3, "weak": 0.3, "war": 0.5, "defense": -0.6, "guar": -0.5},
        "侵攻": {"1": -0.2, "ready": 0.4, "weak": 0.3, "snub": 0.4, "war": 0.4, "defense": -0.9, "guar": -0.8},
    },
    "財閥": {
        "静観": {"1": 0.1, "conc_self": 0.3},
        "浸透": {"1": 0.45, "ore_pot": 0.2, "conc_self": -0.5},
        "工作": {"1": 0.15, "conc_rival": 0.3},
        "要求": {"1": 0.1, "conc_rival": 0.5},
        "示威": {"1": -0.25},
        "友好": {"1": 0.1, "conc_self": 0.4},
        "通牒": {"1": -0.5, "conc_rival": 0.3},
        "侵攻": {"1": -0.6, "conc_self": -0.5},
    },
    "宮廷": {
        "静観": {"1": 0.1},
        "浸透": {"1": 0.05},
        "工作": {"1": 0.45, "weak": 0.3},
        "要求": {"1": 0.05},
        "示威": {"1": -0.1},
        "友好": {"1": 0.3, "lean": 0.3},
        "通牒": {"1": -0.4},
        "侵攻": {"1": -0.5},
    },
    "平和派": {
        "静観": {"1": 0.45},
        "浸透": {"1": 0.2},
        "工作": {"1": -0.05},
        "要求": {"1": -0.05},
        "示威": {"1": -0.4},
        "友好": {"1": 0.3},
        "通牒": {"1": -0.8},
        "侵攻": {"1": -1.0},
    },
    "帝国派": {
        "静観": {"1": 0.1},
        "浸透": {"1": 0.35, "ore_pot": 0.3, "conc_self": -0.4},
        "工作": {"1": 0.2},
        "要求": {"1": 0.1, "ore": 0.4, "conc_rival": 0.3},
        "示威": {"1": 0.0},
        "友好": {"1": 0.1, "conc_self": 0.2},
        "通牒": {"1": -0.3, "ore": 0.4},
        "侵攻": {"1": -0.5},
    },
    "均衡派": {
        "静観": {"1": 0.3, "pressure": -0.4},
        "浸透": {"1": 0.2, "dom": 0.4},
        "工作": {"1": 0.0, "dom": 0.3},
        "要求": {"1": -0.1},
        "示威": {"1": -0.5},
        "友好": {"1": 0.1, "pressure": 0.8, "dom": 0.3},
        "通牒": {"1": -0.9},
        "侵攻": {"1": -1.0},
    },
    "同胞派": {
        "静観": {"1": 0.0},
        "浸透": {"1": 0.0},
        "工作": {"1": 0.35, "weak": 0.3},
        "要求": {"1": 0.25, "weak": 0.2},
        "示威": {"1": 0.1, "tension": 0.3, "unrest": 0.2},
        "友好": {"1": -0.1, "lean": 0.3},
        "通牒": {"1": -0.2, "weak": 0.4, "lean_rival": 0.3, "unrest": 0.3, "defense": -0.5, "guar": -0.4},
        "侵攻": {"1": -0.2, "weak": 0.5, "unrest": 0.4, "snub": 0.4, "defense": -0.8, "guar": -0.7},
    },
    "復讐派": {
        "静観": {"1": 0.05},
        "浸透": {"1": 0.15},
        "工作": {"1": 0.1, "lean_rival": 0.5},
        "要求": {"1": 0.05, "lean_rival": 0.4},
        "示威": {"1": -0.2, "lean_rival": 0.5},
        "友好": {"1": 0.25, "pressure": 0.5},
        "通牒": {"1": -0.6, "lean_rival": 0.6, "war": 0.4},
        "侵攻": {"1": -0.4, "rival_transit": 0.8, "war": 0.2, "defense": -0.6},
    },
    "急進派": {
        "静観": {"1": 0.3},
        "浸透": {"1": 0.1},
        "工作": {"1": 0.35, "weak": 0.3},
        "要求": {"1": 0.0},
        "示威": {"1": -0.3},
        "友好": {"1": -0.1},
        "通牒": {"1": -0.6},
        "侵攻": {"1": -1.0},
    },
}

DEMANDS = {
    "グラウ": {"要求": ["鉱山の利権をグラウ資本に", "北部鉄道の敷設権", "反グラウ新聞の取り締まり"],
             "通牒": ["ザイン峡谷の通過権"]},
    "セレス": {"要求": ["関税の引き下げ", "鉱山の採掘権の国際入札", "借款の担保に税関を"],
             "通牒": []},
    "ラドミール": {"要求": ["ヴェスキ人の自治", "東方教会の保護権", "ラドミール系将校の任用"],
               "通牒": ["東部三郡の自治と駐兵"]},
    "オルネア": {"要求": ["北の要塞の強化と査察", "術式院との共同研究", "グラウ利権の拒否"],
             "通牒": ["対グラウの秘密同盟"]},
}


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- 初期状態
def initial():
    return {
        "週": 0,  # 0 = 王国暦812年 春の第1週
        "緊張": 34.0,
        "大戦": None,
        "協約": {"黎明協約": ["オルネア", "ラドミール"]},  # 秘密の同盟（gm/列強の内情.md）
        "ノルヴァ": {
            "国庫": 12.0, "債務": 180.0, "兵力": 12.0, "要塞": 5.0, "近代化": 25.0,
            "安定": 48.0, "主権": 100.0, "領土": 100.0,
            "傾き": {"グラウ": 5.0, "セレス": 0.0, "ラドミール": 5.0, "オルネア": 0.0},
            "鉱山": {"段階": 0, "利権": {}, "月": 0},
            "保障": {}, "同盟": None, "通過": None, "占領": None, "内乱": 0,
            "失った": None,
        },
        "国": {
            "グラウ": {
                "力": 100, "関係": 5, "備え": 45, "不穏": 15, "情報": .6,
                "派閥": {"参謀本部": ["軍閥", .32], "重工業": ["財閥", .30], "宮廷": ["宮廷", .23], "社民": ["平和派", .15]},
                "首脳": {"名": "皇帝ヴィルフリート二世", "年": 68, "慎重": .7, "野心": .3, "面子": .5},
                "世継ぎ": {"名": "皇太子コンラート", "年": 39, "慎重": .3, "野心": .8, "面子": .8},
                "敵": ["オルネア", "ラドミール"],
            },
            "セレス": {
                "力": 60, "関係": 10, "備え": 30, "不穏": 10, "情報": .5,
                "派閥": {"統一党・帝国派": ["帝国派", .35], "外務省・均衡派": ["均衡派", .35], "自由貿易党": ["平和派", .30]},
                "首脳": {"名": "首相アシュクロフト（統一党）", "年": 61, "慎重": .6, "野心": .4, "面子": .4},
                "敵": ["グラウ"],
            },
            "ラドミール": {
                "力": 75, "関係": 0, "備え": 40, "不穏": 35, "情報": .4,
                "派閥": {"同胞派": ["同胞派", .35], "陸軍": ["軍閥", .20], "財務省": ["平和派", .25], "宮廷神秘派": ["宮廷", .20]},
                "首脳": {"名": "皇帝ミロスラフ四世", "年": 44, "慎重": .4, "野心": .6, "面子": .7},
                "敵": ["グラウ"],
            },
            "オルネア": {
                "力": 70, "関係": 5, "備え": 45, "不穏": 20, "情報": .5,
                "派閥": {"復讐派": ["復讐派", .35], "急進共和派": ["急進派", .25], "銀行団": ["財閥", .25], "植民派": ["帝国派", .15]},
                "首脳": {"名": "首相デュヴァル（第三次内閣）", "年": 57, "慎重": .5, "野心": .4, "面子": .6},
                "敵": ["グラウ"],
            },
        },
        "_内": {p: {"閣議": 1 + i, "要件": None, "拒まれ": -99, "通牒拒まれ": -99, "最後": "静観",
                    "認識": {"傾き": {"グラウ": 5.0, "セレス": 0.0, "ラドミール": 5.0, "オルネア": 0.0}, "守り": 0.2, "安定": 48.0}}
               for i, p in enumerate(POWERS)},
        "圧力": [],  # [週, 国, 強さ]
        "記録": [],
    }


# ---------------------------------------------------------------- 計算の部品
def cred(st, g):
    """保障の重み。条約があっても、保障した国の今の派閥しだいで重くも軽くもなる"""
    nv = st["ノルヴァ"]
    if g not in nv["保障"]:
        return 0.0
    G = st["国"][g]
    tot = sum(v[1] for v in G["派閥"].values())
    bal = sum(v[1] for v in G["派閥"].values() if v[0] in ("均衡派", "復讐派")) / tot
    peace = sum(v[1] for v in G["派閥"].values() if v[0] == "平和派") / tot
    return clip(nv["保障"][g] + 0.5 * bal - 0.3 * peace + 0.1 * G["関係"] / 100)


def defense(nv):
    return clip((nv["兵力"] * 0.6 + nv["要塞"] * 0.5 + 10) / 100)


def stage_of(st, p):
    w = st["週"]
    return w


def features(st, p):
    nv = st["ノルヴァ"]
    P = st["国"][p]
    inner = st["_内"][p]
    per = inner["認識"]
    rivals = P["敵"]
    lean = per["傾き"]
    conc = nv["鉱山"]["利権"]
    w = st["週"]
    guar = 0.0
    for g in nv["保障"]:
        if g != p and (g in rivals or p in st["国"][g]["敵"]):
            guar = max(guar, cred(st, g))
    if nv["同盟"] and nv["同盟"] != p and p in st["国"][nv["同盟"]]["敵"]:
        guar = max(guar, .8)
    pres = 0.0
    for (wk, q, s) in st["圧力"]:
        if q != p and w - wk <= 8:
            pres = max(pres, s)
    war = st["大戦"]
    at_war = 1.0 if war and (p in war["甲"] or p in war["乙"]) else 0.0
    rt = 0.0
    if nv["通過"] and nv["通過"] in rivals:
        rt = 1.0
    return {
        "1": 1.0,
        "lean": clip(lean[p] / 100, -1, 1),
        "lean_rival": clip(max(lean[q] for q in rivals) / 100),
        "dom": clip(max(lean[q] for q in POWERS if q != p) / 100),
        "rel": clip(P["関係"] / 100, -1, 1),
        "defense": per["守り"],
        "guar": guar,
        "tension": st["緊張"] / 100,
        "ore_pot": 1.0 if nv["鉱山"]["段階"] < 3 else 0.5,
        "ore": nv["鉱山"]["段階"] / 3,
        "conc_self": conc.get(p, 0.0),
        "conc_rival": max([conc.get(q, 0.0) for q in rivals] + [0.0]),
        "unrest": P["不穏"] / 100,
        "weak": clip((50 - per["安定"]) / 50),
        "war": at_war,
        "snub": 1.0 if w - inner["拒まれ"] <= 12 or w - inner["通牒拒まれ"] <= 8 else 0.0,
        "ready": P["備え"] / 100,
        "pressure": pres,
        "rival_transit": rt,
    }


def menu(st, p):
    P = st["国"][p]
    inner = st["_内"][p]
    nv = st["ノルヴァ"]
    w = st["週"]
    war = st["大戦"]
    f = features(st, p)
    if nv["失った"] or (nv["占領"] and nv["占領"] == p):
        return ["静観"]
    if w - inner["通牒拒まれ"] <= 6:
        return ["侵攻", "静観", "要求"]
    acts = ["静観", "浸透", "工作", "友好"]
    if inner["要件"] is None and w >= inner.get("次の要求", 0):
        acts.append("要求")
        if p != "セレス" and DEMANDS[p]["通牒"] and (f["rel"] < 0 or f["war"] or f["tension"] > .65 or f["weak"] > .6):
            acts.append("通牒")
    if p != "セレス":
        acts.append("示威")
        if nv["内乱"] >= 3 or (war and f["rival_transit"] and p in (war["甲"] + war["乙"])):
            acts.append("侵攻")
    return acts


def decide(st, p, rng):
    P = st["国"][p]
    L = P["首脳"]
    f = features(st, p)
    acts = menu(st, p)
    tot_w = sum(v[1] for v in P["派閥"].values())
    rows = {}
    for a in acts:
        contrib = {}
        for fname, (arch, wt) in P["派閥"].items():
            u = sum(c * f[k] for k, c in ARCH[arch][a].items())
            contrib[fname] = wt / tot_w * u
        lead = -L["慎重"] * RISK[a] * 0.8 + L["野心"] * RISK[a] * 0.5
        if f["snub"] and a in ("要求", "示威", "通牒", "侵攻"):
            lead += L["面子"] * 0.4
        if a == "静観" and st["週"] - st["_内"][p]["通牒拒まれ"] <= 6:
            lead -= L["面子"] * 0.6  # 通牒を蹴られて引き下がるのは面子が立たない
        rows[a] = (sum(contrib.values()) + lead, contrib, lead)
    temp = 0.10 + 0.10 * (1 - L["慎重"])
    mx = max(r[0] for r in rows.values())
    ex = {a: math.exp((r[0] - mx) / temp) for a, r in rows.items()}
    z = sum(ex.values())
    probs = {a: ex[a] / z for a in acts}
    r = rng.random()
    acc = 0
    choice = acts[-1]
    for a in acts:
        acc += probs[a]
        if r < acc:
            choice = a
            break
    return choice, probs, rows, f, r


# ---------------------------------------------------------------- 行動の効き目
def apply_action(st, p, a, rng, log):
    nv = st["ノルヴァ"]
    P = st["国"][p]
    inner = st["_内"][p]
    w = st["週"]
    inner["最後"] = a
    if a in ("示威", "通牒", "侵攻", "要求"):
        st["圧力"].append([w, p, {"要求": .3, "示威": .5, "通牒": .8, "侵攻": 1.0}[a]])
    st["緊張"] = clip(st["緊張"] + {"示威": 1.5, "通牒": 4, "侵攻": 12}.get(a, 0), 0, 100)
    if a == "要求":
        what = rng.choice(DEMANDS[p]["要求"])
        inner["要件"] = {"種類": "要求", "中身": what, "週": w}
        log(f"{p}：要求「{what}」（返事の期限は4週）")
    elif a == "通牒":
        weak = clip((50 - nv["安定"]) / 50)
        what = "保護条約" if weak > .6 and P["関係"] < 0 else rng.choice(DEMANDS[p]["通牒"])
        inner["要件"] = {"種類": "通牒", "中身": what, "週": w}
        log(f"{p}：最後通牒「{what}」（期限は2週）")
    elif a == "侵攻":
        start_invasion(st, p, rng, log)
    else:
        log(f"{p}：{a}")


def respond(st, p, accept, log=print):
    """要求・通牒への返事。数値を動かす"""
    nv = st["ノルヴァ"]
    P = st["国"][p]
    inner = st["_内"][p]
    req = inner["要件"]
    if not req:
        log(f"{p} からの要件はない")
        return
    w = st["週"]
    if req["種類"] == "要求":
        if accept:
            nv["主権"] -= 1; nv["傾き"][p] += 6; P["関係"] += 8; nv["安定"] -= 2
            inner["次の要求"] = w + 52
        else:
            P["関係"] -= 8; inner["拒まれ"] = w
            inner["次の要求"] = w + 26
    else:
        if accept:
            if req["中身"] == "保護条約":
                nv["失った"] = f"{p}の保護国になった"
            nv["主権"] -= 12; nv["傾き"][p] += 15; P["関係"] += 10; nv["安定"] -= 8
            if req["中身"] == "ザイン峡谷の通過権":
                nv["通過"] = p
        else:
            P["関係"] -= 20; inner["通牒拒まれ"] = w
        inner["次の要求"] = w + 52
    log(f"ノルヴァは{p}の{req['種類']}「{req['中身']}」を{'受けた' if accept else '拒んだ'}")
    inner["要件"] = None
    for k in nv["傾き"]:
        nv["傾き"][k] = clip(nv["傾き"][k], -100, 100)
    P["関係"] = clip(P["関係"], -100, 100)


def intervene_prob(st, q, invader):
    nv = st["ノルヴァ"]
    Q = st["国"][q]
    c = cred(st, q)
    if nv["同盟"] == q:
        c = max(c, .8)
    riv = 1.0 if invader in Q["敵"] else 0.0
    bal = sum(wt for (arch, wt) in Q["派閥"].values() if arch in ("均衡派", "復讐派"))
    p = 0.05 + 0.55 * c + 0.25 * riv * (0.5 + bal) + 0.1 * clip(Q["関係"] / 100, -1, 1) - 0.2 * Q["首脳"]["慎重"]
    if q == "セレス":
        p *= 0.8  # 海の国。陸の戦は渋る
    return clip(p, 0.0, .95)


def start_invasion(st, p, rng, log):
    nv = st["ノルヴァ"]
    if nv.get("侵攻中"):
        return
    nv["侵攻中"] = {"国": p, "週": 0, "援軍": {}}
    log(f"!! {p} がノルヴァに侵攻した")
    for q in POWERS:
        if q == p:
            continue
        ip = intervene_prob(st, q, p)
        if rng.random() < ip:
            nv["侵攻中"]["援軍"][q] = rng.randint(3, 6)
            log(f"   {q} は介入を決めた（{ip:.2f}）。{nv['侵攻中']['援軍'][q]}週で着く")
        else:
            log(f"   {q} は介入しない（{ip:.2f}）")


def invasion_week(st, rng, log):
    nv = st["ノルヴァ"]
    inv = nv["侵攻中"]
    p = inv["国"]
    inv["週"] += 1
    D = defense(nv)
    weak = clip((50 - nv["安定"]) / 50)
    pf = clip(0.14 - 0.20 * D + 0.03 * weak, .01, .25)
    if st["大戦"]:
        pf *= 0.7
    nv["兵力"] = max(2, nv["兵力"] - 0.4)
    nv["安定"] -= 0.5
    arrived = [q for q, t in inv["援軍"].items() if inv["週"] >= t]
    if arrived:
        # 援軍が着いた。侵攻した国は退くか、大戦にするか
        L = st["国"][p]["首脳"]
        if inv.get("戦場") or st["大戦"] or rng.random() < 0.35 + 0.4 * L["野心"] - 0.3 * L["慎重"]:
            if not st["大戦"]:
                begin_great_war(st, rng, log, trigger=p)
            if not inv.get("戦場"):
                log(f"   援軍（{'・'.join(arrived)}）が着いた。戦はノルヴァの地で続く")
                inv["戦場"] = True
            if nv["占領"] is None and rng.random() < pf * 0.5:
                nv["占領"] = p
                log(f"!! 首都リーネが {p} に落ちた（戦場になったまま）")
            return
        log(f"   援軍（{'・'.join(arrived)}）が着き、{p} は兵を引いた")
        nv["侵攻中"] = None
        nv["領土"] -= 3
        st["国"][p]["関係"] -= 20
        return
    if nv["占領"] is None and rng.random() < pf:
        nv["占領"] = p
        log(f"!! 首都リーネが {p} に落ちた（その週の落ちる確率 {pf:.2f}）")
        if not inv["援軍"] and not st["大戦"]:
            nv["失った"] = f"{p}に占領され、保護国にされた"
            nv["侵攻中"] = None
    elif inv["週"] >= 16 and not inv["援軍"]:
        # 四か月持ちこたえた。講和
        nv["侵攻中"] = None
        nv["領土"] -= 10; nv["主権"] -= 10
        st["国"][p]["関係"] -= 10
        log(f"   ノルヴァは四か月持ちこたえ、{p} と講和した（領土−10、主権−10）")


def begin_great_war(st, rng, log, trigger=None):
    a_side = ["グラウ"]
    b_side = []
    for name, mem in st["協約"].items():
        if "グラウ" not in mem:
            b_side += [m for m in mem if m not in b_side]
    for q in ("オルネア", "ラドミール"):
        if q not in b_side and rng.random() < .6:
            b_side.append(q)
    nv = st["ノルヴァ"]
    if "セレス" not in b_side:
        if rng.random() < .25 + .5 * cred(st, "セレス"):
            b_side.append("セレス")
    st["大戦"] = {"甲": a_side, "乙": b_side, "週": 0, "通過決め": False}
    st["緊張"] = 100
    log(f"!!! 大戦が始まった：{'・'.join(a_side)} 対 {'・'.join(b_side)}")


def war_week(st, rng, log):
    war = st["大戦"]
    nv = st["ノルヴァ"]
    war["週"] += 1
    G = st["国"]["グラウ"]
    if not war["通過決め"]:
        war["通過決め"] = True
        stf = sum(wt for (arch, wt) in G["派閥"].values() if arch == "軍閥")
        D = defense(nv)
        guar = max([cred(st, g) for g in nv["保障"] if g != "グラウ"] + [0])
        pt = clip(0.5 + 0.8 * stf - 0.6 * D - 0.4 * guar + 0.15 * nv["鉱山"]["段階"] / 3 + 0.1 * (G["首脳"]["野心"] - G["首脳"]["慎重"]))
        if nv["同盟"] == "グラウ":
            pt = 1.0
        if rng.random() < pt and nv["通過"] != "グラウ" and not nv["占領"]:
            st["_内"]["グラウ"]["要件"] = {"種類": "通牒", "中身": "ザイン峡谷の通過権", "週": st["週"]}
            st["圧力"].append([st["週"], "グラウ", .9])
            log(f"!! グラウが北回り（ザイン峡谷の通過）を決めた（{pt:.2f}）。最後通牒、期限2週")
        else:
            log(f"   グラウは北回りを取らなかった（{pt:.2f}）")
        R = st["国"]["ラドミール"]
        if "ラドミール" in war["乙"] and not st["_内"]["ラドミール"]["要件"] and not nv["占領"]:
            tot = sum(v[1] for v in R["派閥"].values())
            bro = sum(v[1] for v in R["派閥"].values() if v[0] in ("同胞派", "軍閥")) / tot
            guar_r = max([cred(st, g) for g in nv["保障"] if g != "ラドミール" and g in ("グラウ",)] + [0])
            pr = clip(0.15 + 0.6 * bro - 0.5 * D - 0.3 * guar_r - 0.2 * clip(R["関係"] / 100))
            if rng.random() < pr:
                st["_内"]["ラドミール"]["要件"] = {"種類": "通牒", "中身": "東部三郡の自治と駐兵", "週": st["週"]}
                st["圧力"].append([st["週"], "ラドミール", .9])
                log(f"!! ラドミールが大戦を口実に東部の駐兵を求めた（{pr:.2f}）。最後通牒、期限2週")
    if "セレス" not in war["乙"] and "セレス" not in war["甲"]:
        if nv.get("侵攻中") and nv["侵攻中"]["国"] in war["甲"] and rng.random() < .04 + .1 * cred(st, "セレス"):
            war["乙"].append("セレス")
            log("!! セレスが、ノルヴァの中立が破られたことを理由に参戦した")
    if war["週"] >= 52 and rng.random() < 0.008:
        end_great_war(st, rng, log)


def side_strength(st, side):
    s = 0
    for q in side:
        P = st["国"][q]
        k = 0.6 if q == "ラドミール" else 1.0
        if q == "セレス":
            k = 0.7
        s += P["力"] * k * (1 - P["不穏"] / 200)
    return s


def end_great_war(st, rng, log):
    war = st["大戦"]
    nv = st["ノルヴァ"]
    A = side_strength(st, war["甲"]) * (1.15 if nv["通過"] == "グラウ" else 1.0)
    B = side_strength(st, war["乙"])
    a_win = rng.random() < A / (A + B)
    win, lose = (war["甲"], war["乙"]) if a_win else (war["乙"], war["甲"])
    log(f"!!! 大戦が終わった。勝ち：{'・'.join(win)}（甲の勝つ見込み {A/(A+B):.2f}）")
    occ = nv["占領"]
    if occ:
        if occ in win:
            nv["失った"] = f"大戦の講和で{occ}に併合された"
        else:
            log(f"   占領していた{occ}が負け、ノルヴァは戻った（主権−10）")
            nv["占領"] = None; nv["主権"] -= 10
    elif nv["通過"]:
        t = nv["通過"]
        if t in win:
            if rng.random() < .35 * (1 - clip(st["国"][t]["関係"] / 100)):
                nv["失った"] = f"通過を許した{t}が勝ち、そのまま保護国にされた"
        else:
            nv["主権"] -= 10
            if rng.random() < .5:
                nv["領土"] -= 15
                log("   通過を許した罰に、東部をラドミールに割かれた（領土−15）")
    # 勝った側の取り分：弱いノルヴァから領土を削る
    if not nv["失った"]:
        D = defense(nv)
        for q in win:
            Q = st["国"][q]
            claim = sum(wt for (arch, wt) in Q["派閥"].values() if arch in ("軍閥", "同胞派", "帝国派"))
            if Q["関係"] < 20 and rng.random() < claim * (1 - D) * 0.8:
                nv["領土"] -= 15; nv["主権"] -= 8
                log(f"   講和会議で{q}がノルヴァの領土を割かせた（領土−15、主権−8）")
    for q in lose:
        P = st["国"][q]
        P["力"] *= 0.7; P["不穏"] += 30
        for fn, v in P["派閥"].items():
            if v[0] == "軍閥":
                v[1] = max(.05, v[1] - .15)
    for q in win:
        st["国"][q]["首脳"]["野心"] = clip(st["国"][q]["首脳"]["野心"] + .1)
    st["大戦"] = None
    nv["侵攻中"] = None
    st["緊張"] = 20
    nv["通過"] = None


# ---------------------------------------------------------------- 一週の進み
def world_week(st, rng, log):
    st["週"] += 1
    w = st["週"]
    nv = st["ノルヴァ"]
    # 緊張：軍拡の時代なので少しずつ上がる。海の向こうの危機と雪解け
    st["緊張"] += 0.015
    if rng.random() < .003:
        d = rng.uniform(4, 10); st["緊張"] += d; log(f"・海の向こうで危機（緊張+{d:.0f}）")
    if rng.random() < .003:
        d = rng.uniform(3, 8); st["緊張"] -= d; log(f"・列強の会議で雪解け（緊張−{d:.0f}）")
    st["緊張"] = clip(st["緊張"], 0, 100)
    st["圧力"] = [x for x in st["圧力"] if w - x[0] <= 8]
    for p in POWERS:
        P = st["国"][p]
        inner = st["_内"][p]
        P["備え"] += 0.02 * (st["緊張"] + 20 * P["首脳"]["野心"] - P["備え"])
        # 派閥の揺れ
        for v in P["派閥"].values():
            v[1] = max(.03, v[1] + rng.gauss(0, .004))
        s = sum(v[1] for v in P["派閥"].values())
        for v in P["派閥"].values():
            v[1] /= s
        # 認識：情報の質に応じて、本当の値へ寄っていく
        per = inner["認識"]
        k = P["情報"] * 0.1
        for q in POWERS:
            per["傾き"][q] += k * (nv["傾き"][q] - per["傾き"][q])
        per["守り"] += k * (defense(nv) - per["守り"])
        per["安定"] += k * (nv["安定"] - per["安定"])
        if w % 4 == 0:
            P["関係"] *= 0.985
        # 首脳の年
        P["首脳"]["年"] += 1 / 52
        # 期限の切れた要件（返事なし）は拒否とみなす
        req = inner["要件"]
        if req and w - req["週"] > (4 if req["種類"] == "要求" else 2):
            log(f"・{p} の{req['種類']}は期限が切れた（返事なし＝拒否）")
            respond(st, p, False, log)
    # ラドミールの不穏
    R = st["国"]["ラドミール"]
    R["不穏"] = clip(R["不穏"] + 0.03 + 0.0004 * st["緊張"] + rng.gauss(0, .3), 0, 100)
    if R["不穏"] > 75 and rng.random() < .006:
        log("!! ラドミールで革命。帝政が倒れ、臨時政府が立った")
        R["力"] *= 0.6; R["不穏"] = 40
        R["派閥"] = {"臨時政府・穏健": ["平和派", .4], "評議会・急進": ["急進派", .3], "残った将軍たち": ["軍閥", .3]}
        R["首脳"] = {"名": "臨時政府首班", "年": 50, "慎重": .5, "野心": .3, "面子": .4}
        st["協約"].pop("黎明協約", None)
    # グラウの老帝
    G = st["国"]["グラウ"]
    if "世継ぎ" in G and rng.random() < (0.0002 + max(0, G["首脳"]["年"] - 70) * 0.0006):
        log(f"!! {G['首脳']['名']} が崩御。{G['世継ぎ']['名']} が即位")
        G["首脳"] = G.pop("世継ぎ")
        G["首脳"]["名"] = "皇帝コンラート一世"
        for v in G["派閥"].values():
            if v[0] == "軍閥":
                v[1] += .12
    # セレスの総選挙（5年ごと）
    if w % 260 == 0:
        S = st["国"]["セレス"]
        swing = rng.uniform(-.15, .15)
        for fn, v in S["派閥"].items():
            if v[0] == "帝国派":
                v[1] = max(.05, v[1] + swing)
            if v[0] == "平和派":
                v[1] = max(.05, v[1] - swing)
        if swing > 0:
            S["首脳"] = {"名": "統一党の首相", "年": 58, "慎重": .5, "野心": .5, "面子": .5}
        else:
            S["首脳"] = {"名": "自由貿易党の首相", "年": 60, "慎重": .7, "野心": .25, "面子": .35}
        log(f"・セレス総選挙：{S['首脳']['名']}")
    # オルネアの内閣
    if rng.random() < .006:
        O = st["国"]["オルネア"]
        d = rng.uniform(-.08, .08)
        for fn, v in O["派閥"].items():
            if v[0] == "復讐派":
                v[1] = max(.05, v[1] + d)
        O["首脳"]["慎重"] = clip(O["首脳"]["慎重"] + rng.uniform(-.1, .1), .2, .8)
        log(f"・オルネアで内閣が倒れた（復讐派 {'+' if d > 0 else ''}{d:.2f}）")
    # セレスとオルネアの協商
    if "協商" not in st["協約"] and st["緊張"] > 55 and rng.random() < .0015 * st["緊張"] / 50:
        st["協約"]["協商"] = ["セレス", "オルネア"]
        log("・セレスとオルネアが協商を結んだ")
    # 侵攻と大戦
    if nv.get("侵攻中"):
        invasion_week(st, rng, log)
    if st["大戦"]:
        war_week(st, rng, log)
    elif st["緊張"] >= 68 and rng.random() < (st["緊張"] - 62) / 3000:
        begin_great_war(st, rng, log)
    # 閣議
    decisions = []
    for p in POWERS:
        inner = st["_内"][p]
        urgent = (w - inner["拒まれ"] == 1) or (w - inner["通牒拒まれ"] == 1) or (st["大戦"] and st["大戦"]["週"] == 1)
        if w >= inner["閣議"] or urgent:
            gap = 4 if p != "ラドミール" else rng.randint(3, 6)
            inner["閣議"] = w + gap
            if nv["失った"]:
                continue
            choice, probs, rows, f, r = decide(st, p, rng)
            apply_action(st, p, choice, rng, log)
            decisions.append((p, choice, probs, rows, f, r))
    return decisions


def fmt_decision(st, d):
    p, choice, probs, rows, f, r = d
    out = [f"### {p}（{st['国'][p]['首脳']['名']}）→ **{choice}**（乱数 {r:.3f}）"]
    out.append("| 行動 | 確率 | 点 | 首脳 | 派閥の内訳 |")
    out.append("|---|---|---|---|---|")
    for a in sorted(probs, key=lambda a: -probs[a]):
        sc, contrib, lead = rows[a]
        cs = "、".join(f"{k} {v:+.2f}" for k, v in sorted(contrib.items(), key=lambda kv: -abs(kv[1])))
        out.append(f"| {a} | {probs[a]:.2f} | {sc:+.2f} | {lead:+.2f} | {cs} |")
    keys = ["lean", "lean_rival", "rel", "defense", "guar", "tension", "ore", "conc_self", "conc_rival", "weak", "pressure", "snub", "war"]
    out.append("見立て：" + "、".join(f"{k}={f[k]:.2f}" for k in keys))
    return "\n".join(out)


def date_of(w):
    year = 812 + w // 52
    wk = w % 52
    season = ["春", "夏", "秋", "冬"][wk // 13]
    return f"王国暦{year}年 {season} 第{wk % 13 + 1}週"


# ---------------------------------------------------------------- 釣り合い（ノルヴァを簡単な打ち方で動かす）
class Strategy:
    def __init__(self, kind, rng):
        self.kind = kind
        self.rng = rng

    def answer(self, st, p, req):
        nv = st["ノルヴァ"]
        D = defense(nv)
        r = self.rng.random()
        prot = req["中身"] == "保護条約"
        guarded = max([cred(st, g) for g in nv["保障"]] + [0]) > .4 or nv["同盟"]
        if self.kind == "何もしない":
            if req["種類"] == "要求":
                return r < .5
            return r < (.3 if prot else .5)
        if self.kind == "グラウ寄り":
            if p == "グラウ":
                return not prot or r < .5
            if req["種類"] == "要求":
                return r < .3
            return False
        # 均衡
        if req["種類"] == "要求":
            return r < .4
        if prot:
            return False
        if req["中身"] == "ザイン峡谷の通過権":
            return not (D > .35 or guarded)
        return not (D > .3 or guarded)

    def month(self, st, m):
        nv = st["ノルヴァ"]
        rng = self.rng
        mine = nv["鉱山"]
        # 鉱山の利権
        if mine["段階"] == 0 and not mine["利権"]:
            if self.kind == "グラウ寄り" and m >= 2:
                mine["利権"] = {"グラウ": 1.0}; nv["傾き"]["グラウ"] += 25
            elif self.kind == "均衡" and m >= 4:
                mine["利権"] = {"セレス": .5, "オルネア": .5}; nv["傾き"]["セレス"] += 12; nv["傾き"]["オルネア"] += 12
            elif self.kind == "何もしない" and m >= 72:
                best = max(POWERS, key=lambda q: st["国"][q]["関係"])
                mine["利権"] = {best: 1.0}; nv["傾き"][best] += 25
        if self.kind == "グラウ寄り" and m == 6 and not nv["同盟"]:
            nv["同盟"] = "グラウ"; nv["傾き"]["グラウ"] += 30; nv["主権"] -= 5
        if self.kind == "均衡":
            S = st["国"]["セレス"]
            bal = sum(wt for (a, wt) in S["派閥"].values() if a == "均衡派")
            if "セレス" not in nv["保障"] and S["関係"] > 25 and mine["利権"].get("セレス") and rng.random() < .02 + .06 * bal:
                nv["保障"]["セレス"] = .3
            low = min(POWERS, key=lambda q: st["国"][q]["関係"])
            st["国"][low]["関係"] += 2
        # 金
        royalty = 0
        if mine["段階"] == 3:
            royalty = 1.0 if len(mine["利権"]) == 1 else 1.2
        income = 4.0 + nv["近代化"] * 0.02 + royalty
        exp = 3.6 + nv["債務"] * 0.004
        surplus = income - exp + 0.4  # 予算のやりくりの余地
        share = {"何もしない": (.4, 0, .3), "グラウ寄り": (.3, .1, .4), "均衡": (.45, .25, .3)}[self.kind]
        if surplus > 0:
            nv["兵力"] += surplus * share[0] / 2 * (1 - nv["兵力"] / 60)
            nv["要塞"] += surplus * share[1] / 3 * (1 - nv["要塞"] / 50)
            nv["近代化"] += surplus * share[2] / 6 * (1 - nv["近代化"] / 90)
        else:
            nv["債務"] -= surplus
        # 安定
        target = 50 + 0.2 * (nv["近代化"] - 25) - 0.25 * (100 - nv["主権"]) + (5 if mine["段階"] == 3 else 0)
        nv["安定"] += 0.12 * (target - nv["安定"]) + rng.gauss(0, 1.5)
        nv["主権"] = min(100, nv["主権"] + 0.04)
        nv["安定"] = clip(nv["安定"], 0, 100)
        nv["内乱"] = nv["内乱"] + 1 if nv["安定"] < 15 else 0
        for q in POWERS:
            nv["傾き"][q] *= 0.98


def sim_one(kind, seed):
    rng = random.Random(seed)
    st = initial()
    strat = Strategy(kind, rng)
    quiet = lambda *a, **k: None
    acts = {a: 0 for a in ACTIONS}
    wars = 0
    for w in range(WEEKS):
        had_war = bool(st["大戦"])
        decs = world_week(st, rng, quiet)
        if st["大戦"] and not had_war:
            wars += 1
        nv = st["ノルヴァ"]
        for (p, a, *_r) in decs:
            acts[a] += 1
            P = st["国"][p]
            if a == "浸透":
                P["関係"] += 3; nv["傾き"][p] += 2
            elif a == "工作":
                nv["安定"] -= 1.2 * (0.5 if strat.kind == "均衡" else 1.0); nv["傾き"][p] += 2
            elif a == "示威":
                nv["安定"] -= 1; P["関係"] -= 4
            elif a == "友好":
                P["関係"] += 4
                if p == "セレス" and strat.kind == "均衡" and features(st, p)["pressure"] > .5 and "セレス" not in nv["保障"] and rng.random() < .3:
                    nv["保障"]["セレス"] = .3
            P["関係"] = clip(P["関係"], -100, 100)
        for p in POWERS:
            req = st["_内"][p]["要件"]
            if req and st["週"] - req["週"] == 1:
                respond(st, p, strat.answer(st, p, req), quiet)
        if st["週"] % 4 == 0:
            strat.month(st, st["週"] // 4)
            m = nv["鉱山"]
            if m["利権"] and m["段階"] < 3:
                m["月"] += 1
                if m["月"] % 8 == 0:
                    m["段階"] += 1
        if nv["失った"]:
            return False, nv, acts, wars, st["週"]
    ok = nv["主権"] >= 40 and nv["領土"] >= 70
    if not ok:
        nv["失った"] = "主権が名ばかりになった" if nv["主権"] < 40 else "国が切り刻まれた"
    return ok, nv, acts, wars, st["週"]


def balance(n, seed0):
    for kind in ["何もしない", "グラウ寄り", "均衡"]:
        okc = 0
        reasons = {}
        acts_tot = {a: 0 for a in ACTIONS}
        war_tot = 0
        lost_years = []
        sov = []
        for i in range(n):
            ok, nv, acts, wars, w = sim_one(kind, seed0 * 100000 + i)
            okc += ok
            war_tot += wars
            for a in acts:
                acts_tot[a] += acts[a]
            if not ok:
                key = nv["失った"].split("に")[0] if "大戦" not in nv["失った"] else "大戦の講和"
                reasons[nv["失った"]] = reasons.get(nv["失った"], 0) + 1
                lost_years.append(w / 52)
            else:
                sov.append(nv["主権"])
        print(f"## {kind}：独立を保つ {okc / n:.2f}（大戦 平均{war_tot / n:.2f}回）")
        if lost_years:
            ly = sorted(lost_years)
            print(f"   失った年の中央値 {ly[len(ly) // 2]:.1f}年目")
        if sov:
            print(f"   保てたときの主権の平均 {sum(sov) / len(sov):.0f}")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:6]:
            print(f"   {v / n:.3f} {k}")
        tot = sum(acts_tot.values())
        print("   列強の行動：" + "、".join(f"{a} {acts_tot[a] / tot:.2f}" for a in ACTIONS))


# ---------------------------------------------------------------- コマンド
def load():
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n", type=int, default=400)
    a = ap.parse_args()
    if a.cmd == "初期化":
        save(initial()); print("状態.json を作った")
    elif a.cmd == "進める":
        st = load()
        n = int(a.args[0]) if a.args else 1
        seed = a.seed if a.seed is not None else random.SystemRandom().randint(1, 10**9)
        rng = random.Random(seed)
        print(f"seed {seed}")
        for _ in range(n):
            lines = []
            decs = world_week(st, rng, lines.append)
            print(f"\n## {date_of(st['週'])}（週 {st['週']}）　緊張 {st['緊張']:.1f}")
            for l in lines:
                print(l)
            for d in decs:
                print(fmt_decision(st, d))
            st["記録"].append({"週": st["週"], "seed": seed, "出来事": lines})
        save(st)
    elif a.cmd == "返事":
        st = load()
        respond(st, a.args[0], a.args[1] == "受諾")
        save(st)
    elif a.cmd == "記す":
        st = load()
        key, val = a.args[0], a.args[1]
        parts = key.split(".")
        root = st["ノルヴァ"] if parts[0] == "ノルヴァ" else (st["国"][parts[0]] if parts[0] in POWERS else st)
        parts = parts[1:] if parts[0] in POWERS + ["ノルヴァ"] else parts
        cur = root
        for k in parts[:-1]:
            cur = cur[k]
        try:
            v = json.loads(val)
        except json.JSONDecodeError:
            v = val
        cur[parts[-1]] = v
        save(st); print(f"{key} = {v}")
    elif a.cmd == "見る":
        st = load()
        if a.args:
            print(json.dumps(st["国"][a.args[0]], ensure_ascii=False, indent=1))
            print(json.dumps(st["_内"][a.args[0]], ensure_ascii=False, indent=1))
        else:
            print(date_of(st["週"]), "緊張", round(st["緊張"], 1))
            print(json.dumps(st["ノルヴァ"], ensure_ascii=False, indent=1))
            for p in POWERS:
                P = st["国"][p]
                print(p, "関係", P["関係"], "備え", round(P["備え"]), "不穏", round(P["不穏"]),
                      {k: round(v[1], 2) for k, v in P["派閥"].items()}, P["首脳"]["名"])
    elif a.cmd == "釣り合い":
        balance(a.n, a.seed or 1)


if __name__ == "__main__":
    main()
