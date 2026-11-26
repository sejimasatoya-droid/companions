#!/usr/bin/env python3
"""ロシュモール年代記のエンジン。数値・乱数・時間・出来事の山札・人物の企てを扱う。

  python3 engine/rm.py new <出自> [字]          新しく始める（出自：跡取り／代官／塩商の子。力の字は、無ければランダム）
  python3 engine/rm.py power show|use <点> [人前]|set <欄> <値>   一字の力
  python3 engine/rm.py status [--gm]          今の状況（--gm で企て・山札・隠しクロックも）
  python3 engine/rm.py advance [N]            N 週進める（巻き込みなど止まる出来事で止まる。既定 1）
  python3 engine/rm.py undo                   最後の advance の前に戻す
  python3 engine/rm.py roll <修正> [目標]      2d6＋修正（目標があれば成否）
  python3 engine/rm.py check <能力> <目標> [修正]  主人公の能力で判定（2d6＋能力修正＋修正）
  python3 engine/rm.py set <道> <値>           値を直接変える（例：town.銀 120、flags.市場の許し true）
  python3 engine/rm.py add <道> <値>           値を足す（例：npc.トマ.好意 1、clocks.霧の満ち 1）
  python3 engine/rm.py routine 稽古=2 人と話す=3 休む=1   週の過ごし方（6 日）
  python3 engine/rm.py log "<文>"              記録に一行足す
  python3 engine/rm.py memory <人物> "<文>"    人物が主人公について覚えたこと（その人が後で持ち出す）
  python3 engine/rm.py scheme <人物> help|hinder|fail|done|show   企てを手伝う／邪魔する／潰す／成らせる
  python3 engine/rm.py scheme <人物> new <型> "<名>" "<狙い>"      新しい企てを型から作る（GM が段の文を直す）
  python3 engine/rm.py thread close <id>|tag <タグ>   筋を閉じる／そのタグの札をすべて山から抜く
  python3 engine/rm.py daily add <人物> "<文>"  日常の一手を足す
  python3 engine/rm.py project add "<名>" <週> [銀]   計画を始める
"""
import json, os, random, shutil, sys, glob, re

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
SAVE = os.path.join(HERE, "save", "state.json")
SNAP = os.path.join(HERE, "save", "snapshots")
LOG = os.path.join(GAME, "log.md")
GM_LOG = os.path.join(GAME, "gm", "伏せた出来事.md")

SEASONS = {1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋", 12: "冬"}
ABIL = ["体", "技", "知", "話", "心"]
HOOK_STOP = {"頼み", "板挟み", "巻き添え", "秘密", "取り立て", "濡れ衣", "誘い", "打ち明け", "対決", "誓い", "逃げ込み",
             "置き土産"}


def load(name):
    with open(os.path.join(DATA, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


_cal = None


def calendar():
    global _cal
    if _cal is None:
        _cal = load("calendar")
    return _cal


def cal(week):
    """week 0 = 311年 種月 第1週"""
    c = calendar()
    m0 = c["start_month"] - 1 + week // 4
    return c["start_year"] + m0 // 12, m0 % 12 + 1, week % 4 + 1


def cal_str(week):
    y, m, w = cal(week)
    name = calendar()["months"][m - 1]
    return f"公国暦{y}年 {name}（{m}月・{SEASONS[m]}）第{w}週"


def d(n):
    return random.randint(1, n)


def mod(v):
    return (v - 10) // 2 if v >= 10 else -((11 - v) // 2)


# ---------------------------------------------------------------- 状態
def save(st):
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def state():
    if not os.path.exists(SAVE):
        sys.exit("セーブがない。python3 engine/rm.py new <出自> で始める")
    with open(SAVE, encoding="utf-8") as f:
        return json.load(f)


DRY = False


def append_md(path, line):
    if DRY:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new and path == GM_LOG:
            f.write("# 伏せた出来事（GM 用。プレイヤーは読まない）\n\n")
        f.write(line + "\n")


def names(st):
    y, m, w = cal(st["week"])
    ns = dict(st["town"])
    ns.update({k: v["val"] for k, v in st["clocks"].items()})
    ns.update({f"flag_{k}": v for k, v in st["flags"].items()})
    for n, r in st["npcs"].items():
        ns[f"好意_{n}"] = r.get("好意", 0)
        ns[f"信頼_{n}"] = r.get("信頼", 0)
        ns[f"段_{n}"] = (r.get("企て") or {}).get("段", 0)
        ns[f"企て_{n}"] = (r.get("企て") or {}).get("id", "")
    ns.update({"季節": SEASONS[m], "月": m, "年": y, "週": st["week"], "閉じた": st["threads_closed"],
               "タグ": st["tags_closed"], "完成": st["done_projects"]})
    return ns


class Flag(dict):
    def __missing__(self, k):
        if k.startswith("flag_"):
            return False
        raise NameError(k)


def cond(st, expr):
    if not expr:
        return True
    try:
        return bool(eval(expr, {"__builtins__": {}}, Flag(names(st))))
    except Exception as e:
        print(f"  （条件の誤り：{expr} → {e}）")
        return False


def apply(st, eff, out=None):
    for path, v in (eff or {}).items():
        parts = path.split(".")
        if parts[0] == "npc":
            r = st["npcs"].setdefault(parts[1], {})
            key = parts[2]
            r[key] = r.get(key, 0) + v if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            if key in ("好意", "信頼"):
                r[key] = max(-5, min(5, r[key]))
        elif parts[0] == "clocks":
            c = st["clocks"][parts[1]]
            c["val"] = max(0, min(c["max"], c["val"] + v))
            if out:
                clock_check(st, parts[1], out)
        elif parts[0] == "flags":
            st["flags"][parts[1]] = v
        elif parts[0] == "economy":
            st["economy"][parts[1]] = round(st["economy"].get(parts[1], 0) + v, 2)
        elif parts[0] == "town":
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                st["town"][parts[1]] = round(st["town"].get(parts[1], 0) + v, 2)
                if parts[1] in ("治安", "町の声", "公の覚え"):
                    st["town"][parts[1]] = max(0, min(100, st["town"][parts[1]]))
            else:
                st["town"][parts[1]] = v
        elif parts[0] == "hero":
            h = st["hero"]
            if parts[1] in h.get("能力", {}):
                h["能力"][parts[1]] += v
            else:
                h[parts[1]] = h.get(parts[1], 0) + v if isinstance(v, (int, float)) else v


class Out:
    def __init__(self, st):
        self.st, self.lines, self.stops, self.hidden = st, [], [], 0

    def report(self, text, stop=False, visible=True, log=True):
        if not visible:
            append_md(GM_LOG, f"- {cal_str(self.st['week'])}：{text}")
            self.hidden += 1
            if stop:
                self.stops.append("（伏せた出来事。gm/伏せた出来事.md の最新行を GM が見る）")
                self.lines.append("  ■停止（伏せた出来事あり：GM 確認）")
            return
        self.lines.append(("  ■ " if stop else "  ・ ") + text)
        if stop:
            self.stops.append(text)
        if log:
            append_md(LOG, f"- {cal_str(self.st['week'])}：{text}")

    def note(self, text):
        """GM への注記。記録には残さない"""
        self.lines.append("    → " + text)


# ---------------------------------------------------------------- クロック（節目は一周に一度）
def clock_check(st, cid, out):
    c = st["clocks"][cid]
    fired = c.setdefault("鳴った", [])
    for k, th in sorted(load("clocks")[cid].get("節目", {}).items(), key=lambda x: int(x[0])):
        k = int(k)
        if c["val"] >= k and k not in fired:
            fired.append(k)
            out.report(f"【{c['name']} {c['val']}/{c['max']}】{th['text']}", stop=th.get("stop", True),
                       visible=not c.get("hidden"))
            apply(st, th.get("effects"), out)
        elif c["val"] >= k and k in fired and c.get("下がった_" + str(k)):
            c.pop("下がった_" + str(k))
            out.report(f"【{c['name']} {c['val']}/{c['max']}】（再び {k} に戻った）", stop=True, visible=not c.get("hidden"))
            out.note("同じ文を繰り返さない。前とは違うきっかけ・違う人物から、再燃として描く")
    for k in fired:
        if c["val"] < k:
            c["下がった_" + str(k)] = True


def clocks_week(st, out):
    defs = load("clocks")
    for cid, c in st["clocks"].items():
        df = defs.get(cid, {})
        if c.get("止める") or c["val"] >= c["max"]:
            continue
        p = df.get("p", 0)
        for m in df.get("mods", []):
            if cond(st, m["if"]):
                p += m["p"]
        if random.random() < p:
            c["val"] += 1
            clock_check(st, cid, out)


# ---------------------------------------------------------------- 暦・収支
def calendar_week(st, out):
    y, m, w = cal(st["week"])
    for ev in calendar()["festivals"]:
        if ev["month"] == m and ev["week"] == w and cond(st, ev.get("if")):
            out.report(f"〔暦〕{ev['text']}", stop=ev.get("stop", False))
            apply(st, ev.get("effects"), out)


def money_week(st, out):
    t = st["town"]
    y, m, w = cal(st["week"])
    inc = st["economy"]["週の入り"][SEASONS[m]] + st["economy"].get("足し", 0)
    cost = st["economy"]["週の出"]
    t["銀"] = round(t["銀"] + inc - cost, 2)
    if SEASONS[m] == "冬":
        t["蔵"] = round(t["蔵"] - 1, 1)
    if m == 7 and w == 4:
        harvest = 14 + d(6) + d(6) - 7 - (2 if st["clocks"].get("霧の満ち", {}).get("val", 0) >= 5 else 0)
        t["蔵"] = round(t["蔵"] + harvest, 1)
        out.report(f"〔暦〕刈り入れが終わった。蔵に麦 {harvest} 週分が入った（いま {t['蔵']}）")
    if w == 4:
        out.lines.append(f"  ・ 月末：金庫 {t['銀']} 銀（週の入り {inc}・週の出 {cost}）、蔵 {t['蔵']} 週分")
    if t["銀"] < 0 and not st["flags"].get("金庫が空"):
        st["flags"]["金庫が空"] = True
        out.report("金庫が底をついた。兵と役人の給金が払えない", stop=True)
    elif t["銀"] >= 0:
        st["flags"]["金庫が空"] = False
    if t["蔵"] <= 2 and SEASONS[m] == "冬" and not st["flags"].get("飢えの兆し"):
        st["flags"]["飢えの兆し"] = True
        out.report("蔵の麦が尽きかけている。冬を越せない家が出る", stop=True)


# ---------------------------------------------------------------- 人物の企て（巻き込み）
def scheme_defs():
    return load("schemes")


def scheme_week(st, out):
    """人物の企てが、主人公と関係なく進む。段が進むと、主人公を巻き込むフックが出る。
    語り手：一週に進む企ては多くて一つ（economy.企ての率、既定 0.35）。同じ人は「間」の週だけ空ける"""
    sdefs = scheme_defs()
    cands = []
    for n, r in st["npcs"].items():
        sc = r.get("企て")
        if not sc or r.get("不在"):
            continue
        df = sc.get("def") or sdefs.get(sc["id"])
        if not df or st["week"] - sc.get("前の週", -99) < df.get("間", 3):
            continue
        cands.append((n, r, sc, df, max(0.03, df.get("p", 0.15) + 0.07 * sc.get("押し", 0))))
    if not cands or random.random() > st["economy"].get("企ての率", 0.35):
        return
    n, r, sc, df, _ = random.choices(cands, weights=[c[4] for c in cands])[0]
    sc["段"] += 1
    sc["前の週"] = st["week"]
    stages = df["段"]
    if sc["段"] > len(stages):
        scheme_end(st, n, r, df, True, out)
        return
    s = stages[sc["段"] - 1]
    hook = s.get("巻き込み", "なし")
    with_ = f"（相手：{s['相手']}）" if s.get("相手") else ""
    out.report(f"〈{n}〉企て「{df['名']}」{sc['段']}/{len(stages)}［{hook}］{s['text']}{with_}",
               stop=s.get("stop", hook in HOOK_STOP), visible=not s.get("hidden"))
    apply(st, s.get("effects"), out)
    if hook in HOOK_STOP:
        out.note(f"巻き込み「{hook}」：{load('hooks').get(hook, '')}")
    if r.get("記憶"):
        out.note(f"{n}が覚えていること（場面で持ち出す）：{r['記憶'][-1]}")
    # ぶつかり：同じものを狙う別の人の企てが、近ごろ同じところまで来ていれば、板挟みにする
    for t in s.get("ぶつかる", []):
        st.setdefault("ぶつかり", {}).setdefault(t, {})[n] = st["week"]
        rivals = [m for m, w in st["ぶつかり"][t].items() if m != n and st["week"] - w <= 12]
        if rivals:
            out.report(f"〈{n}・{'・'.join(rivals)}〉の企てが「{t}」でぶつかった。どちらも主人公に味方を求めてくる", stop=True)
            out.note("板挟み：片方につけば、もう片方の好意 −1〜−2。両方を立てる道を探すなら判定（話、目標 10 以上）。黙っていれば両方の信頼 −1")


def scheme_end(st, n, r, df, success, out):
    res = df.get("成った" if success else "潰れた", {})
    text = res.get("text", "企てが成った" if success else "企てが潰れた")
    out.report(f"〈{n}〉企て「{df['名']}」が{'成った' if success else '潰れた'}。{text}", stop=True)
    apply(st, res.get("effects"), out)
    r.setdefault("終えた企て", []).append({"id": r["企て"]["id"], "名": df["名"], "成否": "成" if success else "潰",
                                       "週": st["week"]})
    nxt = res.get("次")
    r["企て"] = None
    if nxt and nxt in scheme_defs():
        r["企て"] = {"id": nxt, "段": 0, "押し": 0, "前の週": st["week"]}
        out.note(f"{n}は次に「{scheme_defs()[nxt]['名']}」に動きだす")
    else:
        out.note(f"{n}の企てが空いた。人物シートの「欲」と結果から、次の企てを決める"
                 f"（engine/trait.py 企て で型を引ける → scheme {n} new <型> \"<名>\" \"<狙い>\"）。"
                 f"結果に合わせて、人物の「いま」欄も書き換える（成った人は変わり、潰れた人も変わる）")


def scheme_cmd(st, args):
    n = args[0]
    r = st["npcs"][n]
    op = args[1] if len(args) > 1 else "show"
    sc = r.get("企て")
    out = Out(st)
    if op == "show":
        if not sc:
            print(f"{n}：企てなし")
        else:
            df = sc.get("def") or scheme_defs()[sc["id"]]
            print(f"{n}：「{df['名']}」 段 {sc['段']}/{len(df['段'])}、押し {sc.get('押し', 0)}、週の進み p={df.get('p', .15)}")
            print(f"  狙い：{df.get('狙い', '')}")
            for i, s in enumerate(df["段"], 1):
                mark = "✓" if i <= sc["段"] else " "
                print(f"  {mark}{i}［{s.get('巻き込み', 'なし')}］{s['text']}")
        return
    if op in ("help", "hinder"):
        sc["押し"] = sc.get("押し", 0) + (1 if op == "help" else -1)
        print(f"{n}の企ての押し → {sc['押し']}（週の進みが ±0.07）")
    elif op in ("fail", "done"):
        df = sc.get("def") or scheme_defs()[sc["id"]]
        scheme_end(st, n, r, df, op == "done", out)
    elif op == "new":
        typ, name, aim = args[2], args[3], args[4] if len(args) > 4 else ""
        tpl = load("scheme_types")[typ]
        r["企て"] = {"id": f"{n}_{len(r.get('終えた企て', []))}_{typ}", "段": 0, "押し": 0, "前の週": st["week"],
                   "def": {"名": name, "狙い": aim, "p": tpl.get("p", 0.15), "間": 3,
                           "段": [dict(s) for s in tpl["段"]], "成った": {"text": tpl["成った"]},
                           "潰れた": {"text": tpl["潰れた"]}}}
        print(f"{n}に企て「{name}」（型：{typ}）を作った。段の文は型のままなので、"
              f"save/state.json の npcs.{n}.企て.def.段 を、この人の言葉と町の具体に書き直すこと")
    for l in out.lines:
        print(l)
    save(st)


# ---------------------------------------------------------------- 出来事の山札と筋
def build_deck(st, out):
    """季節の初めに山札を作る。引いた札は戻さない。閉じた筋・閉じたタグの札は入らない"""
    y, m, w = cal(st["week"])
    season = SEASONS[m]
    deck = []
    for th in load("threads"):
        if th["id"] in st["threads_open"] or th["id"] in st["threads_closed"]:
            continue
        if set(th.get("tags", [])) & set(st["tags_closed"]):
            continue
        if th.get("季節") and season not in th["季節"]:
            continue
        if cond(st, th.get("if")):
            deck += [("筋", th["id"])] * th.get("w", 1)
    for c in load("cards"):
        if c["id"] in st["cards_used"] or (set(c.get("tags", [])) & set(st["tags_closed"])):
            continue
        if c.get("季節") and season not in c["季節"]:
            continue
        if cond(st, c.get("if")):
            deck += [("札", c["id"])] * c.get("w", 1)
    random.shuffle(deck)
    seen, uniq = set(), []
    for x in deck:  # 重みは「早く出やすい」に使い、同じ札は一枚だけ残す
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    st["deck"] = [list(x) for x in uniq]
    out.lines.append(f"  ・ （{season}の山札を切った：{len(uniq)} 枚）")


def deck_week(st, out):
    y, m, w = cal(st["week"])
    if w == 1 and m in (3, 6, 9, 12) or not st.get("deck_built"):
        build_deck(st, out)
        st["deck_built"] = True
    # 開いている筋は、自分の間合いで次の段へ進む（同じ文はくり返さない）
    thdefs = {t["id"]: t for t in load("threads")}
    # 語り手：この週すでに巻き込みで止まっていれば、出来事は控えめにする（一週に大きなことは一つ）
    if out.stops and random.random() > 0.3:
        return
    for tid, o in list(st["threads_open"].items()):
        th = thdefs[tid]
        if set(th.get("tags", [])) & set(st["tags_closed"]):
            st["threads_open"].pop(tid)
            st["threads_closed"].append(tid)
            continue
        stage = th["段"][o["段"]] if o["段"] < len(th["段"]) else None
        if stage is None:
            st["threads_open"].pop(tid)
            st["threads_closed"].append(tid)
            out.note(f"筋「{th['名']}」は最後の段まで来た。決着がまだなら GM が場面で決め、thread close {tid}")
            continue
        if st["week"] - o["週"] < stage.get("間", 2) or random.random() > 0.5:
            continue
        if stage.get("if") and not cond(st, stage["if"]):
            continue
        show_stage(st, th, o["段"], out)
        o["段"] += 1
        o["週"] = st["week"]
        return  # 一週に進む筋は一つ
    if random.random() > st["economy"].get("出来事の率", 0.25):
        return
    if len(st["threads_open"]) >= 3:
        return
    while st["deck"]:
        kind, cid = st["deck"].pop(0)
        if kind == "筋":
            th = thdefs[cid]
            if cond(st, th.get("if")) and not set(th.get("tags", [])) & set(st["tags_closed"]):
                st["threads_open"][cid] = {"段": 1, "週": st["week"]}
                show_stage(st, th, 0, out)
                return
        else:
            c = next(c for c in load("cards") if c["id"] == cid)
            if cond(st, c.get("if")) and not set(c.get("tags", [])) & set(st["tags_closed"]):
                st["cards_used"].append(cid)
                out.report(f"《出来事・{c.get('層', '町')}》{c['text']}", stop=c.get("stop", True), visible=c.get("visible", True))
                apply(st, c.get("effects"), out)
                if c.get("seed"):
                    out.note("種：" + c["seed"])
                if c.get("人"):
                    out.note("関わる人：" + "・".join(c["人"]) + "（その人の企て・欲と結びつけて描く）")
                return
    if not st.get("deck_empty_noted"):
        st["deck_empty_noted"] = True
        out.note("この季節の山札が尽きた。静かな季節にするか、data/cards.json に今の町に合う札を足す")


def show_stage(st, th, i, out):
    s = th["段"][i]
    out.report(f"《{th['名']} {i + 1}/{len(th['段'])}・{th.get('層', '町')}》{s['text']}", stop=s.get("stop", bool(s.get("seed"))),
               visible=s.get("visible", True))
    apply(st, s.get("effects"), out)
    if s.get("seed"):
        out.note("種：" + s["seed"])
    if s.get("人"):
        out.note("関わる人：" + "・".join(s["人"]) + "（その人の企て・欲と結びつけて描く）")


# ---------------------------------------------------------------- 日常の一手と町のざわめき
def daily_week(st, out):
    """毎週、だれか一人が、主人公と関係なく暮らしの一手を打つ。人物が生きて見えるように"""
    daily = st["daily"]
    cands = [n for n, lines in daily.items() if lines and n not in st["daily_recent"]
             and not st["npcs"].get(n, {}).get("不在")]
    if not cands:
        if not any(daily.values()) and not st.get("daily_empty_noted"):
            st["daily_empty_noted"] = True
            out.note("日常の一手がすべて尽きた。人物のいまに合わせて daily add で足す")
        return
    n = random.choice(cands)
    line = daily[n].pop(random.randrange(len(daily[n])))
    st["daily_recent"] = (st["daily_recent"] + [n])[-4:]
    out.report(f"〔{n}〕{line}", stop=False)
    if not daily[n]:
        out.note(f"{n}の日常の一手が尽きた。いまの{n}らしい一手を daily add で 3〜5 つ足す")


def rumor_month(st, out):
    y, m, w = cal(st["week"])
    if w != 4:
        return
    R = load("rumors")
    pool = st.setdefault("rumor_pool", {})
    picked = []
    for _ in range(2):
        parts = []
        for key in ("人", "場所", "こと"):
            left = pool.get(key) or []
            if not left:
                left = list(range(len(R[key])))
                random.shuffle(left)
            parts.append(R[key][left.pop()])
            pool[key] = left
        picked.append(f"{parts[0]}が、{parts[1]}で、{parts[2]}")
    out.report("〔町のざわめき〕" + "／".join(picked), stop=False)
    out.note("ざわめきは背景。主人公が拾えば場面にしてよく、拾わなければ流れる")


# ---------------------------------------------------------------- 主人公の週・計画
POWER_STEPS = [0, 30, 80, 160, 280]  # 段 2〜5 に上がるのに要る、ためた経験（段 5 まで、毎週使っておよそ 1 年半）


def hero_week(st, out):
    """能力は 18 で止まる（311年 長夜月、プレイヤーの希望で 13 の上限をなくした）"""
    h = st["hero"]
    acts = load("activities")
    rt = h.get("過ごし方", {})
    for a, days in rt.items():
        ab = acts.get(a, {}).get("能力")
        if not ab:
            continue
        h["経験"][ab] = h["経験"].get(ab, 0) + days
        need = max(6, (h["能力"][ab] - 6) * 3)
        if h["能力"][ab] >= 18:
            h["経験"][ab] = 0
        elif h["経験"][ab] >= need:
            h["経験"][ab] -= need
            h["能力"][ab] += 1
            out.report(f"主人公の{ab}が伸びた：{h['能力'][ab] - 1} → {h['能力'][ab]}", stop=False)
    pw = h.get("力")
    if pw:
        pw["上限"] = 4 + 2 * pw["段"]
        pw["点"] = min(pw["上限"], pw["点"] + pw["上限"] // 2 + rt.get("休む", 0))
        if cal(st["week"])[2] == 4 and pw.get("怪しさ", 0) > 0:
            pw["怪しさ"] -= 1
    active = sum(v for k, v in rt.items() if k != "休む")
    h["疲れ"] = round(max(0, h["疲れ"] + 0.12 * active - 0.5 - 0.4 * rt.get("休む", 0)), 2)
    if h["疲れ"] >= 3:
        out.report("主人公はひどく疲れている（疲れ 3 以上。判定 −2）", stop=not st["flags"].get("疲れを知らせた"))
        st["flags"]["疲れを知らせた"] = True
    else:
        st["flags"]["疲れを知らせた"] = False


def power_cmd(st, args):
    """一字の力。show／use <点> [人前]／set <欄> <値>"""
    pw = st["hero"].get("力")
    op = args[0] if args else "show"
    if op == "show":
        print(f"力「{pw['字']}」（{pw['読み']}）{('— ' + pw['名']) if pw.get('名') else ''}　段 {pw['段']}/5　"
              f"力の点 {pw['点']}/{pw['上限']}　経験 {pw['経験']}（次の段まで {POWER_STEPS[pw['段']] - pw['経験'] if pw['段'] < 5 else '―'}）　怪しさ {pw.get('怪しさ', 0)}")
        for k in ("できること", "伸びた先", "代価", "知られると", "決めごと"):
            if pw.get(k):
                print(f"  {k}：{pw[k]}")
        return
    if op == "use":
        n = int(args[1])
        public = "人前" in args[2:]
        if n > pw["点"]:
            print(f"力の点が足りない（{pw['点']}）。無理に使うなら、GM が代価を重くする")
            return
        pw["点"] -= n
        pw["経験"] += n
        out = Out(st)
        print(f"力「{pw['字']}」を使った（−{n}、残り {pw['点']}/{pw['上限']}）。代価：{pw['代価']}")
        while pw["段"] < 5 and pw["経験"] >= POWER_STEPS[pw["段"]]:
            pw["段"] += 1
            pw["上限"] = 4 + 2 * pw["段"]
            out.report(f"力「{pw['字']}」が段 {pw['段']} に上がった", stop=False)
            out.note(f"GM：段が上がった。できることを一つ広げて、power set できること で書き直す（伸びた先：{pw['伸びた先']}）")
        if public or n >= 4:
            r1, r2 = d(6), d(6)
            s = r1 + r2 + pw.get("怪しさ", 0) + (3 if public else 0) + n // 2
            print(f"  気づかれるか 🎲{r1}+{r2}＋怪しさ{pw.get('怪しさ', 0)}{'＋人前3' if public else ''}＋{n // 2} ＝ {s}（13 以上で噂）")
            if public:
                pw["怪しさ"] = pw.get("怪しさ", 0) + 1
            if s >= 13:
                apply(st, {"clocks.力の噂": 1}, out)
                out.report(f"主人公の力「{pw['字']}」を、誰かが見た。噂が広がりはじめる（知られると：{pw['知られると']}）", stop=True)
        for l in out.lines:
            print(l)
        append_md(LOG, f"- {cal_str(st['week'])}：力「{pw['字']}」を使った（{n} 点{'、人前で' if public else ''}）")
    elif op == "set":
        pw[args[1]] = parse_val(args[2]) if args[1] in ("段", "点", "経験", "怪しさ") else args[2]
        print(f"力の{args[1]} → {args[2]}")
    save(st)


def projects_week(st, out):
    for p in list(st["projects"]):
        p["残り"] -= 1
        if p["残り"] <= 0:
            st["projects"].remove(p)
            st["done_projects"].append(p["名"])
            out.report(f"計画「{p['名']}」が仕上がった", stop=True)
            apply(st, p.get("effects"), out)


# ---------------------------------------------------------------- 進める
def advance(st, n):
    snap(st)
    for _ in range(n):
        out = Out(st)
        print(f"== {cal_str(st['week'])} ==")
        calendar_week(st, out)
        money_week(st, out)
        clocks_week(st, out)
        scheme_week(st, out)
        deck_week(st, out)
        daily_week(st, out)
        rumor_month(st, out)
        projects_week(st, out)
        hero_week(st, out)
        for l in out.lines:
            print(l)
        if out.hidden:
            print(f"  （伏せた出来事 {out.hidden} 件 → gm/）")
        st["week"] += 1
        if out.stops:
            print(f"\n→ 止まった：{cal_str(st['week'] - 1)} の終わり。場面にする")
            break
    save(st)


def snap(st):
    os.makedirs(SNAP, exist_ok=True)
    with open(os.path.join(SNAP, f"{st['week']:05d}.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    files = sorted(glob.glob(os.path.join(SNAP, "*.json")))
    for f in files[:-12]:
        os.remove(f)


def undo():
    files = sorted(glob.glob(os.path.join(SNAP, "*.json")))
    if not files:
        sys.exit("戻せる記録がない")
    shutil.copy(files[-1], SAVE)
    os.remove(files[-1])
    print(f"{os.path.basename(files[-1])} の前に戻した（log.md に書かれた行は GM が手で消す）")


# ---------------------------------------------------------------- 表示
def status(st, gm):
    h, t = st["hero"], st["town"]
    print(f"■ {cal_str(st['week'])}")
    print(f"主人公：{h.get('名', '（未定）')}（{h.get('出自', '')}・{h.get('年齢', '?')}歳） 疲れ {h['疲れ']}")
    print("  能力：" + "  ".join(f"{a} {h['能力'][a]}({mod(h['能力'][a]):+d})" for a in ABIL))
    pw = h.get("力")
    if pw:
        print(f"  力：「{pw['字']}」{('（' + pw['名'] + '）') if pw.get('名') else ''} 段 {pw['段']}/5　力の点 {pw['点']}/{pw['上限']}　怪しさ {pw.get('怪しさ', 0)}")
    if h.get("過ごし方"):
        print("  過ごし方：" + "、".join(f"{k}{v}" for k, v in h["過ごし方"].items()))
    print(f"町：金庫 {t['銀']} 銀　蔵 {t['蔵']} 週分　人口 {t['人口']}　治安 {t['治安']}　町の声 {t['町の声']}　公の覚え {t['公の覚え']}")
    vis = [f"{c['name']} {c['val']}/{c['max']}" for c in st["clocks"].values() if not c.get("hidden")]
    print("情勢：" + "　".join(vis))
    print("人物（好意／信頼／借り。借り＋は主人公が負っている）：")
    for n, r in st["npcs"].items():
        if r.get("不在"):
            continue
        print(f"  {n}：{r.get('好意', 0):+d}／{r.get('信頼', 0):+d}／{r.get('借り', 0):+d}  {r.get('いま', '')}")
    if st["threads_open"]:
        thd = {x["id"]: x for x in load("threads")}
        print("動いている筋：" + "、".join(f"{thd[k]['名']}({v['段']}/{len(thd[k]['段'])})" for k, v in st["threads_open"].items()))
    if st["projects"]:
        print("計画：" + "、".join(f"{p['名']}（残り{p['残り']}週）" for p in st["projects"]))
    if gm:
        print("\n［GM］企て：")
        for n, r in st["npcs"].items():
            sc = r.get("企て")
            if sc:
                df = sc.get("def") or scheme_defs()[sc["id"]]
                print(f"  {n}：「{df['名']}」{sc['段']}/{len(df['段'])} 押し{sc.get('押し', 0)}")
            else:
                print(f"  {n}：（企てなし → 決める）")
            if r.get("記憶"):
                print(f"      覚えている：{r['記憶'][-1]}")
        print("［GM］隠しクロック：" + "　".join(f"{c['name']} {c['val']}/{c['max']}" for c in st["clocks"].values() if c.get("hidden")))
        print(f"［GM］山札 残り {len(st['deck'])} 枚　閉じた筋 {len(st['threads_closed'])}　閉じたタグ {st['tags_closed']}")


# ---------------------------------------------------------------- 始める
def new(origin, ji=None):
    st = load("initial_state")
    org = load("origins")
    if origin not in org:
        sys.exit("出自は " + "／".join(org) + " のどれか")
    o = org[origin]
    st["hero"]["出自"] = origin
    for k, v in o["能力"].items():
        st["hero"]["能力"][k] += v
    pool = load("kanji")
    if ji:
        kj = next((x for x in pool if x["字"] == ji), None) or {"字": ji, "読み": "", "できること": "", "伸びた先": "",
                                                              "代価": "", "知られると": ""}
    else:
        kj = random.choice(pool)
    st["hero"]["力"] = dict(kj, 段=1, 経験=0, 点=6, 上限=6, 怪しさ=0, 名="", 決めごと="")
    apply(st, o.get("effects"))
    for n, v in o.get("人物", {}).items():
        for k, x in v.items():
            st["npcs"][n][k] = st["npcs"][n].get(k, 0) + x
    st["daily"] = load("daily")
    os.makedirs(os.path.dirname(SAVE), exist_ok=True)
    save(st)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("# 記録\n\n")
    append_md(LOG, f"- {cal_str(0)}：{o['始まり']}")
    print(f"始めた：{origin}。{o['始まり']}")
    print(f"力の字：「{kj['字']}」（{kj.get('読み', '')}）。表の芽：{kj.get('できること', '（GM とプレイヤーで決める）')}")
    print("→ 字から、プレイヤーと一緒に力の形を決め、power set 名／できること／代価／決めごと で書く")
    print("名前・年齢・見た目・ひとこと（譲れないこと）を決めたら、set hero.名 … などで入れる")


def sim(weeks, seeds):
    """セーブを変えずに、新しく始めた町を weeks 週ずつ seeds 通り回して、出来事の数と重なりを数える"""
    global DRY
    DRY = True
    import collections, io, contextlib
    tot = collections.Counter()
    dup = 0
    for seed in range(seeds):
        random.seed(seed)
        st = load("initial_state")
        st["daily"] = load("daily")
        st["hero"]["力"] = dict(random.choice(load("kanji")), 段=1, 経験=0, 点=6, 上限=6, 怪しさ=0)
        texts = collections.Counter()
        for _ in range(weeks):
            out = Out(st)
            for f in (calendar_week, money_week, clocks_week, scheme_week, deck_week, daily_week, rumor_month,
                      projects_week, hero_week):
                f(st, out)
            for l in out.lines:
                if l.startswith("    →"):
                    continue
                kind = "巻き込み" if "〉企て" in l else "筋" if "《" in l and "》" in l and "《出来事" not in l else \
                    "札" if "《出来事" in l else "日常" if l.strip("・ ■").startswith("〔") and "〔暦〕" not in l and "ざわめき" not in l else \
                    "ざわめき" if "ざわめき" in l else "節目" if "【" in l else "暦" if "〔暦〕" in l else "その他"
                tot[kind] += 1
                if "■" in l:
                    tot["止まる"] += 1
                m_ = re.search(r"・(個人|町|公国|世界)》", l)
                if m_:
                    tot["層：" + m_.group(1)] += 1
                if kind not in ("暦", "その他"):
                    key = re.sub(r"[0-9.]+", "", l)
                    texts[key] += 1
            st["week"] += 1
        dup += sum(v - 1 for v in texts.values() if v > 1)
    print(f"{weeks} 週 × {seeds} 通りの平均（1 通りあたり）")
    for k, v in tot.most_common():
        print(f"  {k}：{v / seeds:.1f}")
    print(f"  同じ文が二度以上出た回数：{dup / seeds:.2f}")


def parse_val(v):
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "sim":
        sim(int(a[1]) if len(a) > 1 else 96, int(a[2]) if len(a) > 2 else 20)
        return
    if cmd == "new":
        new(a[1], a[2] if len(a) > 2 else None)
        return
    if cmd == "undo":
        undo()
        return
    if cmd == "roll":
        m = int(a[1]) if len(a) > 1 else 0
        r1, r2 = d(6), d(6)
        s = r1 + r2 + m
        res = ""
        if len(a) > 2:
            tgt = int(a[2])
            res = "　大成功" if r1 + r2 == 12 else "　大失敗" if r1 + r2 == 2 else (
                "　成功" if s >= tgt else "　条件つき（あと 1〜2）" if s >= tgt - 2 else "　失敗")
            res += f"（目標 {tgt}）"
        print(f"🎲 {r1}+{r2}{m:+d} ＝ {s}{res}")
        return
    st = state()
    if cmd == "status":
        status(st, "--gm" in a)
    elif cmd == "advance":
        advance(st, int(a[1]) if len(a) > 1 else 1)
    elif cmd == "check":
        ab, tgt = a[1], int(a[2])
        extra = int(a[3]) if len(a) > 3 else 0
        tired = -2 if st["hero"]["疲れ"] >= 3 else 0
        m = mod(st["hero"]["能力"][ab]) + extra + tired
        sys.argv = ["", "roll", str(m), str(tgt)]
        print(f"{ab} {st['hero']['能力'][ab]}（修正 {m:+d}{'、疲れ −2 込み' if tired else ''}）")
        main()
        return
    elif cmd in ("set", "add"):
        path, v = a[1], parse_val(a[2])
        if cmd == "set":
            parts = path.split(".")
            obj = st
            for p in parts[:-1]:
                obj = obj["npcs"] if p == "npc" else obj.setdefault(p, {})
            obj[parts[-1]] = v
        else:
            out = Out(st)
            apply(st, {path: v}, out)
            for l in out.lines:
                print(l)
        save(st)
        print(f"{path} → {v}（{cmd}）")
    elif cmd == "routine":
        rt = {}
        for kv in a[1:]:
            k, v = kv.split("=")
            rt[k] = int(v)
        if sum(rt.values()) != 6:
            print(f"（注意：合計 {sum(rt.values())} 日。1 週は 6 日）")
        unknown = [k for k in rt if k not in load("activities")]
        if unknown:
            print("（知らない過ごし方：" + "、".join(unknown) + "。data/activities.json を見る）")
        st["hero"]["過ごし方"] = rt
        save(st)
        print("過ごし方：" + "、".join(f"{k}{v}" for k, v in rt.items()))
    elif cmd == "log":
        append_md(LOG, f"- {cal_str(st['week'])}：{a[1]}")
        print("記録した")
    elif cmd == "memory":
        st["npcs"][a[1]].setdefault("記憶", []).append(f"{cal_str(st['week'])}：{a[2]}")
        save(st)
        print(f"{a[1]}が覚えた：{a[2]}")
    elif cmd == "power":
        power_cmd(st, a[1:])
    elif cmd == "scheme":
        scheme_cmd(st, a[1:])
    elif cmd == "thread":
        if a[1] == "close":
            st["threads_open"].pop(a[2], None)
            st["threads_closed"].append(a[2])
            print(f"筋 {a[2]} を閉じた。もう出ない")
        elif a[1] == "tag":
            st["tags_closed"].append(a[2])
            st["deck"] = [x for x in st["deck"] if not (set(
                next((t.get("tags", []) for t in load("threads") + load("cards") if t["id"] == x[1]), [])) & {a[2]})]
            print(f"タグ「{a[2]}」を閉じた。この問題につながる筋と札は、もう山に入らない（蒸し返さない）")
        save(st)
    elif cmd == "daily":
        st["daily"].setdefault(a[2], []).append(a[3])
        save(st)
        print(f"{a[2]}の日常の一手を足した")
    elif cmd == "project":
        name, weeks = a[2], int(a[3])
        cost = float(a[4]) if len(a) > 4 else 0
        st["town"]["銀"] = round(st["town"]["銀"] - cost, 2)
        st["projects"].append({"名": name, "残り": weeks})
        save(st)
        print(f"計画「{name}」を始めた（{weeks} 週、銀 {cost}）。仕上がりの効き目は GM が set/add で入れる")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
