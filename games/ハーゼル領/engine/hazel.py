#!/usr/bin/env python3
"""ハーゼル領記 エンジン

数値・時間・乱数・クロック・勢力と人物の自律行動・ランダムイベントを機械的に処理する。
物語・人物の演技・判断は GM（Claude）が行う。

使い方（games/ハーゼル領/ で）:
  python3 engine/hazel.py status            現在の状況
  python3 engine/hazel.py advance [N]       N 週進める（重要な出来事で自動停止。既定 1）
  python3 engine/hazel.py check 能力 目標値 [--bonus N] [--note 説明]
  python3 engine/hazel.py persuade 人物 --dc 14 [--match N] [--loss N] [--status -3] [--proof] [--bonus N]
  python3 engine/hazel.py roll 2d6+1        任意の乱数
  python3 engine/hazel.py adj パス 増減 理由  例: adj npcs.マグダ.信頼 1 "狼柵を約束した"
  python3 engine/hazel.py set パス 値 理由    例: set flags.読み書きの師 true "司祭が引き受けた"
  python3 engine/hazel.py routine 読み書き=3 遊ぶ=2 人と話す=1   主人公の週の過ごし方（計 6 日）
  python3 engine/hazel.py project list|tree|start ID [人数]|assign ID 人数|cancel ID
  python3 engine/hazel.py npc next 人物 週後 "内容" [--stop] [--hidden] [--effects JSON]
  python3 engine/hazel.py watch add "条件式" "内容" [--stop] [--hidden] [--effects JSON]
  python3 engine/hazel.py rumor add "内容" 段階 | rumor list
  python3 engine/hazel.py battle --a JSON --b JSON [--terrain 平地|森|丘|防御] [--a-lead N] [--b-lead N] [--named 名前,名前]
  python3 engine/hazel.py jikuri 戻す|進める --stage 1 --size 小物|人|道具|動物|荷車|小屋|家|畑 [--living] [--witness 人数]
  python3 engine/hazel.py magic 呪文名 [--witness N]          系統魔法（見識など）
  python3 engine/hazel.py policy show | policy set 年貢 軽い "理由"
  python3 engine/hazel.py appoint 家令 ヴィクトル [--discretion 大|小] [--policy "方針"]
  python3 engine/hazel.py page start 小姓|従士 | page resolve 成功|失敗 | page end
  python3 engine/hazel.py court --ours 証拠 --theirs 証拠 [--our-voice N] [--their-voice N] [--their-mod N]
  python3 engine/hazel.py treaty add|break|list 相手 種類 "条件"
  python3 engine/hazel.py marriage list | marriage engage 名前 "条件" | marriage break "理由"
  python3 engine/hazel.py impression 人物 "印象"   人物の主人公への印象を書き換える
  python3 engine/hazel.py log "内容"
  python3 engine/hazel.py init               初期状態を作り直す（今の状態は消える）
"""
import argparse
import json
import math
import os
import random
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import world as WORLD  # 世界シミュレーション（engine/world.py）
import war as WAR  # 戦の台帳（engine/war.py）

BASE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(BASE)
DATA = os.path.join(BASE, "data")
SAVE = os.path.join(BASE, "save", "state.json")
INIT = os.path.join(DATA, "initial_state.json")
LOG_MD = os.path.join(GAME, "log.md")
GM_LOG = os.path.join(GAME, "gm", "伏せた出来事.md")

MONTHS = ["霜月", "灯月", "芽月", "花月", "緑月", "草月", "陽月", "麦月", "実月", "葡萄月", "屠月", "聖月"]
SEASON_OF = {1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋", 12: "冬"}
START_YEAR = 812
START_OFFSET = 8  # 812年 芽月 第1週 = 812年の通算8週目（0始まり）
SPARE_LABOR = {"春": 60, "夏": 40, "秋": 30, "冬": 100}  # 人口1180のときの週あたり余力（人）
BASE_POP = 1180


# ---------------------------------------------------------------- 入出力
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SNAP_DIR = os.path.join(BASE, "save", "snapshots")
SNAP_KEEP = 40
SNAP_LABEL = ""


def snapshot(label):
    """いまの状態を保存する（刻戻り用）。古いものから消す"""
    if not os.path.exists(SAVE):
        return
    os.makedirs(SNAP_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    n = int(files[-1].split("_")[0]) + 1 if files else 1
    st = load_json(SAVE)
    st["_snap"] = {"n": n, "label": label, "when": cal_str(st["week"])}
    with open(os.path.join(SNAP_DIR, f"{n:05d}_.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    for old in files[:-SNAP_KEEP + 1] if len(files) >= SNAP_KEEP else []:
        os.remove(os.path.join(SNAP_DIR, old))


def save_state(st):
    os.makedirs(os.path.dirname(SAVE), exist_ok=True)
    tmp = SAVE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SAVE)


def load_state():
    if not os.path.exists(SAVE):
        st = load_json(INIT)
        save_state(st)
        return st
    return load_json(SAVE)


def defs(name):
    return load_json(os.path.join(DATA, name + ".json"))


def append_md(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new and path == GM_LOG:
            f.write("# 伏せた出来事（GM 用。プレイヤーは読まないでね）\n\n")
        f.write(line.rstrip() + "\n")


# ---------------------------------------------------------------- 暦
def cal(w):
    t = w + START_OFFSET
    year = START_YEAR + t // 48
    month = (t % 48) // 4 + 1
    week = t % 4 + 1
    return year, month, week


def cal_str(w):
    y, m, wk = cal(w)
    return f"聖暦{y}年 {MONTHS[m-1]}（{m}月・{SEASON_OF[m]}）第{wk}週"


def age(st, w=None):
    w = st["week"] if w is None else w
    y, m, _ = cal(w)
    by, bm = st["protagonist"]["born"]
    return y - by - (1 if m < bm else 0)


# ---------------------------------------------------------------- 乱数
def d(n):
    return random.randint(1, n)


def roll_expr(expr):
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr.replace(" ", ""))
    if not m:
        raise SystemExit(f"乱数の式が読めません: {expr}")
    k = int(m.group(1) or 1)
    n = int(m.group(2))
    b = int(m.group(3) or 0)
    rs = [d(n) for _ in range(k)]
    return rs, sum(rs) + b


def p_week(p_season):
    p_season = max(0.0, min(1.0, p_season))
    return 1 - (1 - p_season) ** (1 / 12)


# ---------------------------------------------------------------- 状態の操作
def get_path(st, path):
    cur = st
    for k in path.split("."):
        cur = cur[k]
    return cur


def set_path(st, path, value):
    keys = path.split(".")
    cur = st
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


CLAMP = {"民心": (0, 100), "治安": (0, 100), "開発": (0, 100), "衛生": (0, 100), "森の健全度": (0, 100),
         "主家の覚え": (0, 100), "注目度": (0, 100), "信頼": (-5, 5), "好意": (-5, 5), "警戒": (0, 5),
         "態度": (-5, 5)}


def apply_effects(st, effects, out=None):
    """effects: {"domain.治安": -5, "flags.xxx": true, "clocks.森": 1}"""
    for path, v in (effects or {}).items():
        if isinstance(v, bool) or isinstance(v, str) or v is None:
            set_path(st, path, v)
            continue
        try:
            cur = get_path(st, path)
        except (KeyError, TypeError):
            cur = 0
        new = cur + v
        key = path.split(".")[-1]
        if path.startswith("clocks."):
            cid = path.split(".")[1]
            if CLOCKS.get(cid, {}).get("retired"):
                continue  # 退いたクロックは、ほかの手でも動かない
            mx = CLOCKS.get(cid, {}).get("max", 99)
            new = max(0, min(mx, new))
            if out is not None and new != cur:
                check_thresholds(st, cid, cur, new, out)
        elif key in CLAMP:
            lo, hi = CLAMP[key]
            new = max(lo, min(hi, new))
        if isinstance(new, float):
            new = round(new, 2)
        set_path(st, path, new)


def namespace(st):
    """条件式で使える名前。領の数値・クロック・季節・人物の関係値（人物_信頼）・旗（flag_名前）など"""
    y, m, wk = cal(st["week"])
    ns = dict(st["domain"])
    ns.update({k: (0 if CLOCKS.get(k, {}).get("retired") else v) for k, v in st["clocks"].items()})  # 退いたクロックは条件では 0
    ns.update({"年": y, "月": m, "週": wk, "季節": SEASON_OF[m], "年齢": age(st), "通算週": st["week"],
               "作柄": st.get("harvest") or "未定"})
    for name, r in st["npcs"].items():
        for k in ("信頼", "好意", "警戒", "借り"):
            ns[f"{name}_{k}"] = r.get(k, 0)
    for k, v in st["flags"].items():
        ns[f"flag_{k}"] = v
    for k, v in st["factions"].items():
        for kk, vv in v.items():
            if isinstance(vv, (int, float)):
                ns[f"{k}_{kk}"] = vv
    ns["完成"] = set(st["projects_done"])
    for k, v in st["protagonist"]["abilities"].items():
        ns[f"主人公_{k}"] = v
    for k, v in st["protagonist"].get("cards", {}).items():
        ns[f"カード_{k}"] = v
    ns["軍_常備兵"] = st["military"].get("常備兵", 0)
    pg = st.get("page") or {}
    ns["城での評判"] = pg.get("評判", 0)
    for k, v in (pg.get("派閥") or {}).items():
        ns[f"page_{k}"] = v
    ns["疲労"] = st["protagonist"].get("fatigue", 0)
    return ns


class FlagDefault(dict):
    def __missing__(self, key):
        if key.startswith("flag_"):
            return False
        raise NameError(key)


def cond(st, expr):
    if not expr:
        return True
    ns = FlagDefault(namespace(st))
    try:
        return bool(eval(expr, {"__builtins__": {}, "min": min, "max": max}, ns))
    except NameError as e:
        print(f"[警告] 条件式の名前が不明: {expr} ({e})", file=sys.stderr)
        return False


# ---------------------------------------------------------------- 報告
class Out:
    def __init__(self, st):
        self.st = st
        self.lines = []
        self.stops = []
        self.hidden = 0

    def report(self, text, stop=False, visible=True, log=False):
        w = self.st["week"]
        if visible:
            mark = "■停止" if stop else "・"
            self.lines.append(f"  {mark} {text}")
            if stop:
                self.stops.append(text)
            if stop or log:
                append_md(LOG_MD, f"- {cal_str(w)}：{text}")
        else:
            self.hidden += 1
            append_md(GM_LOG, f"- {cal_str(w)}：{text}")
            if stop:
                # 伏せた出来事でも GM が判断すべきものは止める（内容は GM ファイルへ）
                self.stops.append("（伏せた出来事。gm/伏せた出来事.md の最新行を GM が確認）")
                self.lines.append("  ■停止 （伏せた出来事あり：GM 確認）")


# ---------------------------------------------------------------- クロック
CLOCKS = {}


def check_thresholds(st, cid, old, new, out):
    c = CLOCKS[cid]
    for t in range(old + 1, new + 1):
        th = c.get("thresholds", {}).get(str(t))
        if not th:
            continue
        vis = th.get("visible", c.get("visible", True))
        out.report(f"【{c['name']} {t}/{c['max']}】{th['text']}", stop=th.get("stop", True), visible=vis)
        apply_effects(st, th.get("effects"), out)


def tick_clocks(st, out):
    for cid, c in CLOCKS.items():
        if st["flags"].get(f"停止_{cid}") or c.get("retired"):
            continue
        cur = st["clocks"].get(cid, 0)
        if cur >= c["max"]:
            continue
        p = c.get("p_season", 0)
        for m in c.get("mods", []):
            if cond(st, m["if"]):
                p += m["p_season"]
        if c.get("only_if") and not cond(st, c["only_if"]):
            continue
        p += policy_effects(st)["clock"].get(cid, 0)
        if random.random() < p_week(p):
            apply_effects(st, {f"clocks.{cid}": 1}, out)
            if not c.get("visible", True):
                append_md(GM_LOG, f"- {cal_str(st['week'])}：隠しクロック「{c['name']}」が {cur+1}/{c['max']} に")


# ---------------------------------------------------------------- 経済
def econ_week(st, out):
    dm = st["domain"]
    y, m, wk = cal(st["week"])
    fl = st["flags"]
    pop_k = dm["人口"] / BASE_POP

    # 毎週の小さな収入
    mill = 0 if fl.get("水車故障") else (20 + (6 if "水車の改良" in st["projects_done"] else 0) + (2 if "水車の修理" in st["projects_done"] else 0))
    toll = 10 * (0.5 if dm["治安"] < 40 else 1.0) * (1.5 if "道の整備" in st["projects_done"] else 1.0)
    weekly = (mill + 5 + toll + 10) / 48 * pop_k + st["domain_extra"].get("週収入", 0)
    dm["財貨"] = round(dm["財貨"] + weekly, 2)

    def money(amount, why):
        dm["財貨"] = round(dm["財貨"] + amount, 2)
        out.report(f"{why}：{amount:+.1f} 金貨（財貨 {dm['財貨']:.1f}）")

    # 暦の決まった収支
    if (m, wk) == (3, 1):
        dues = 25 * (2 if (not CLOCKS.get("カルディア国境の緊張", {}).get("retired") and st["clocks"].get("カルディア国境の緊張", 0) >= 4) or st["flags"].get("東の再動員") else 1)
        money(-dues, "辺境伯への軍役代納金")
        money(20 * pop_k, "冬越しの年貢の残り")
    # 季節ごとの石材と木材（石切り場・森の手入れ）
    if (m, wk) in ((3, 1), (6, 1), (9, 1), (12, 1)):
        if "石切り場" in st["projects_done"]:
            dm["石材"] = round(dm.get("石材", 0) + 1, 2)
            out.report(f"石切り場から、季節の石が出た（石材 {dm['石材']}）")
        if st["flags"].get("沼鉄"):
            n_iron = 1 + (1 if st["flags"].get("鉄の炉") else 0)
            dm["鉄"] = round(dm.get("鉄", 0) + n_iron, 2)
            out.report(f"湿地の沼鉄から、季節の鉄がとれた（鉄 {dm['鉄']}）")
        if "森の手入れ" in st["projects_done"]:
            dm["木材"] = round(dm.get("木材", 0) + 1, 2)
            out.report(f"森の手入れで、季節の木材がとれた（木材 {dm['木材']}）")
        if st["flags"].get("鋸場"):
            dm["木材"] = round(dm.get("木材", 0) + 1, 2)
            out.report(f"水の鋸場で、季節の板がとれた（木材 {dm['木材']}）")
        if st["flags"].get("煉瓦窯"):
            dm["石材"] = round(dm.get("石材", 0) + 1, 2)
            out.report(f"煉瓦の窯から、季節の煉瓦が出た（石材 {dm['石材']}）")
    # ヴァルクとの夏・冬の交易：約束があれば、山の飢えが一つ和らぐ
    if (m, wk) in ((6, 3), (12, 2)) and any(t.get("相手") == "ヴァルク" for t in st.get("treaties", [])):
        cur = st["clocks"].get("ヴァルク族の飢え", 0)
        if 0 < cur < 6:
            st["clocks"]["ヴァルク族の飢え"] = cur - 1
            out.report(f"ヴァルクとの{'夏' if m == 6 else '冬'}の交易：山に麦が上がる（ヴァルク族の飢え {cur}→{cur-1}）", log=True)
    if (m, wk) == (4, 4):
        money(20 * pop_k * (1.3 if "羊の選抜" in st["projects_done"] else 1.0), "羊毛の売り上げ")
    if (m, wk) == (6, 1):
        r = d(20) + (1 if dm["開発"] >= 40 else 0) + (2 if st["flags"].get("溜め池") else 0) + {"凶作": -6, "豊作": 6}.get(st.get("world_harvest"), 0)
        st["harvest"] = "凶作" if r <= 3 else ("豊作" if r >= 17 else "平年")
        hint = {"凶作": "麦の育ちが悪い。村々に不安が広がる", "平年": "麦はまずまずの育ち", "豊作": "麦の穂が重い。今年は豊作になりそうだ"}
        out.report(f"作柄の見通し：{hint[st['harvest']]}（🎲{r}）", stop=st["harvest"] == "凶作", log=True)
    if (m, wk) == (8, 4):
        h = st.get("harvest") or "平年"
        delta = {"凶作": -2.5, "平年": 0.3, "豊作": 2.0}[h] + (dm["開発"] - 28) / 40
        dm["食糧"] = round(dm["食糧"] + delta, 2)
        out.report(f"夏の刈り入れ（{h}）：食糧備蓄 {delta:+.1f}（→ {dm['食糧']:.1f} か月分）", log=True)
    if (m, wk) == (9, 2):
        h = st.get("harvest") or "平年"
        k = {"凶作": 0.6, "平年": 1.0, "豊作": 1.2}[h]
        k *= 1 + (dm["開発"] - 28) / 100
        k *= 0.75 if dm["民心"] < 25 else (0.9 if dm["民心"] < 40 else 1.0)
        pol = policy_effects(st)
        money((190 * pol["tax"] + 70 * pol["demesne"]) * k * pop_k, f"秋の年貢と直営地の収穫（{h}）")
        money(-10, "教会への寄進")
        money(-round(dm["負債"] * dm["利率"], 1), "借金の利子")
        st["harvest"] = None
    if (m, wk) == (1, 1):
        money(-20, "辺境伯への年始の献上")
        money(20 * (dm["森の健全度"] / 70) * policy_effects(st)["winter"], "薪・炭・放牧料")
        money(round(15 * random.uniform(0.3, 1.7), 1), "魔石の税")
    if (m, wk) == (3, 2):
        if d(20) <= 2 and not st["flags"].get("川の堤"):
            out.report("春の雪解けでハーゼル川が氾濫した。ミルデ村の畑が水をかぶる", stop=True)
            apply_effects(st, {"domain.食糧": -0.5, "domain.民心": -3}, out)
    if (m, wk) == (12, 1):
        if d(20) <= 3:
            out.report("厳しい冬になりそうだ。森から獣の声が近い", stop=True)
            apply_effects(st, {"domain.食糧": -0.5, "clocks.黒の森の異変": 1}, out)

    # 人口の増え方（821年 実月に足した）：季節の終わりに、年の伸びの 4 分の 1 ずつ
    if wk == 4 and m in (3, 6, 9, 12):
        done = set(st["projects_done"])
        rate = 0.005 + max(0, dm["衛生"] - 50) / 2000 + (0.005 if dm["民心"] > 60 else 0) + (0.005 if dm["食糧"] > 6 else 0)
        rate += 0.003 * sum(1 for k in ("施療所", "産婆の手洗い", "種痘") if k in done)
        if dm.get("名誉", 0) >= 70 and dm["治安"] >= 70 and "市の開設" in done:
            rate += 0.01  # よそから来て住みつく者
        if dm["食糧"] < 2 or dm["民心"] < 30:
            rate = min(rate, 0.0)
        add = round(dm["人口"] * rate / 4)
        if add:
            dm["人口"] += add
            out.report(f"季節の終わり：人口 +{add}（→ {dm['人口']}。年に {rate*100:.1f}% の伸び）")
    # 月末の固定費
    if wk == 4:
        cost = st["domain_extra"].get("月の固定費", 21.7)
        if fl.get("給金遅配"):
            cost -= 8.7
        dm["財貨"] = round(dm["財貨"] - cost, 2)
        out.report(f"月末の支払い（館・給金・修繕）：-{cost:.1f} 金貨（財貨 {dm['財貨']:.1f}）")
        if dm["財貨"] < 0 and not fl.get("赤字中"):
            fl["赤字中"] = True
            out.report("金庫が底をついた。当主は給金の遅配か、借金か、何かを売るかを迫られる", stop=True)
        if dm["財貨"] >= 0:
            fl["赤字中"] = False
        if fl.get("給金遅配"):
            apply_effects(st, {"domain.民心": -1}, out)
        for eff in policy_effects(st)["monthly"]:
            apply_effects(st, eff, out)
        # 何もなければ、民心と治安はゆっくり平常（民心55・治安50）へ戻る
        for k, base in (("民心", 55), ("治安", 50)):
            if dm[k] < base and not fl.get("給金遅配") and not fl.get("飢え"):
                dm[k] += 1
            elif dm[k] > base + 15:
                dm[k] -= 1

    # 飢え
    if dm["食糧"] < 0:
        apply_effects(st, {"domain.民心": -1, "domain.人口": -round(dm["人口"] * 0.002)}, out)
        if not fl.get("飢え"):
            fl["飢え"] = True
            out.report("蓄えが尽きた。領内に飢えが広がり始めた", stop=True)
    else:
        fl["飢え"] = False

    # 借金の期限
    if (y, m, wk) == tuple(st["domain_extra"]["借金期限"]) and dm["負債"] > 0:
        out.report(f"借金の元金 {dm['負債']:.0f} 金貨の返済期限が来た", stop=True)


# ---------------------------------------------------------------- 計画
def need_xp(v):
    """次の 1 に要る経験点（821年 花月に改め）：（値 − 5）² ＋ 10。サイコロは振らない。年齢の上限もない"""
    return max(10, (v - 5) ** 2 + 10)


def grow(st, h, ab, cap, out):
    """経験点がたまったら、必ず 1 上がる。cap は使わない（年齢の上限はなくした）"""
    while h["xp"].get(ab, 0) >= need_xp(h["abilities"][ab]):
        v = h["abilities"][ab]
        h["xp"][ab] -= need_xp(v)
        h["abilities"][ab] = v + 1
        out.report(f"主人公の{ab}が伸びた：{v} → {v+1}", log=True)


def gain_xp(st, ab, res):
    """場面の判定に成功すると、その能力に経験点が入る（成功 +2、大成功 +5）"""
    h = st["protagonist"]
    if ab not in h["abilities"]:
        return
    add = 5 if res == "大成功" else 2 if res in ("成功",) or (isinstance(res, str) and res.startswith("成功")) else 0
    if add:
        h["xp"][ab] = h["xp"].get(ab, 0) + add
        print(f"  経験点：{ab} +{add}")


def labor_available(st):
    y, m, wk = cal(st["week"])
    return round(SPARE_LABOR[SEASON_OF[m]] * st["domain"]["人口"] / BASE_POP * policy_effects(st)["labor"] - st["military"].get("徴募兵", 0))


def projects_week(st, out):
    pdefs = defs("projects")
    avail = labor_available(st)
    used = 0
    for p in st["projects_active"]:
        pd = pdefs[p["id"]]
        need_people = p["labor"] < pd.get("labor", 0)  # 手間が済んだ計画は、人を放して日数だけ待つ
        people = min(p["people"], max(0, avail - used)) if need_people else 0
        used += people
        p["labor"] += people
        p["weeks"] += 1
        if p.get("hero_days_needed"):
            p["hero_days"] = p.get("hero_days", 0) + st["protagonist"]["routine"].get("計画", 0)
        done = p["labor"] >= pd.get("labor", 0) and p["weeks"] >= pd.get("min_weeks", 1) \
            and p.get("hero_days", 0) >= pd.get("hero_days", 0)
        if done:
            st["projects_done"].append(p["id"])
            out.report(f"計画「{pd['name']}」が完成した。{pd.get('done_text', '')}", stop=True)
            apply_effects(st, pd.get("effects"), out)
            p["finished"] = True
    st["projects_active"] = [p for p in st["projects_active"] if not p.get("finished")]
    if used > avail:
        out.report("人手が足りず、計画の進みが遅れている")


# ---------------------------------------------------------------- 主人公
def mod(v):
    """能力の修正（2d6 用）：（能力 − 6）÷ 2。6〜7 で 0、8〜9 で +1、10〜11 で +2、12〜13 で +3 …"""
    return math.floor((v - 6) / 2)


def roll2d6():
    a, b = d(6), d(6)
    return a, b, a + b


def grade(r, total, dc, partial=1):
    """2d6 の結果：12 大成功／2 大失敗／目標値以上 成功／partial 以内の不足 代償つき／それ以外 失敗"""
    if r == 12:
        return "大成功"
    if r == 2:
        return "大失敗"
    if total >= dc:
        return "成功"
    if total >= dc - partial:
        return "代償つき"
    return "失敗"


def fatigue_pen(f):
    """疲労による判定の罰：2 以上で −1、3 以上で −2"""
    return -2 if f >= 3 else (-1 if f >= 2 else 0)


def auto_routine(st, out):
    """疲労などの条件で、週の過ごし方を自動で切り替える（st["auto_routine"]）"""
    for rule in st.get("auto_routine", []):
        if cond(st, rule["if"]) and st["protagonist"]["routine"] != rule["routine"]:
            st["protagonist"]["routine"] = dict(rule["routine"])
            out.report(f"過ごし方を自動で切り替えた（{rule.get('why', rule['if'])}）：" + " / ".join(f"{k}{v}日" for k, v in rule["routine"].items()))
            break


def hero_week(st, out):
    auto_routine(st, out)
    h = st["protagonist"]
    acts = defs("activities")
    rt = h["routine"]
    a = age(st)
    cap_body = 12 if a < 12 else 16 if a < 17 else 18
    cap_mind = 15 if a < 12 else 17 if a < 17 else 18
    active = 0
    for act, days in rt.items():
        ad = acts.get(act)
        if not ad or days <= 0:
            continue
        if ad.get("requires") and not cond(st, ad["requires"]):
            out.report(f"「{act}」はまだできない（{ad.get('requires_text', ad['requires'])}）。その日は遊んで過ごした")
            continue
        if act != "休む":
            active += days
        ab = ad.get("ability")
        if ab:
            learn = 1.25 if h.get("cards", {}).get("発達と学習の心理", 0) >= 1 and ab in ("知識", "礼法") else 1.0
            rate = ad.get("rate", 1)
            for ri in ad.get("rate_if", []):
                if cond(st, ri["if"]):
                    rate = ri["rate"]
                    break
            h["xp"][ab] = h["xp"].get(ab, 0) + days * rate * learn
            cap = cap_body if ab in ("体力", "武芸") else cap_mind
            grow(st, h, ab, cap, out)
    # 魔力の保留（821年 花月の取り決め）：月の初めに 50、師について学んでいる季節は季節の初めに 200 を解き放つ
    y_, m_, wk_ = cal(st["week"])
    if h.get("魔力の保留", 0) > 0 and wk_ == 1:
        rel = 50 + (200 if m_ in (3, 6, 9, 12) and st["flags"].get("師に学ぶ") else 0)
        rel = min(rel, h["魔力の保留"])
        h["魔力の保留"] = round(h["魔力の保留"] - rel, 2)
        h["xp"]["魔力"] = h["xp"].get("魔力", 0) + rel
        append_md(GM_LOG, f"- {cal_str(st['week'])}：魔力の保留から {rel} を解き放った（残り {h['魔力の保留']}）")
    # 過ごし方に入っていない能力も、ほかの道でたまった経験点（見識の暮らしなど）で伸びる判定をする
    trained = {acts[a].get("ability") for a in rt if a in acts}
    for ab in h["abilities"]:
        if ab not in trained:
            grow(st, h, ab, cap_body if ab in ("体力", "武芸") else cap_mind, out)
    rest = rt.get("休む", 0)
    if "魔力点上限" in h:
        h["魔力点上限"] = h["abilities"]["魔力"] * 2
        h["魔力点"] = min(h["魔力点上限"], h["魔力点"] + h["魔力点上限"] // 2 + rest)
        use = st["flags"].get("見識をよく使う")
        if use and h.get("系統") == "見識":
            # 日々の暮らしで見識を使う（帳簿の品、麦、薬草、銀など）。旗の値が、毎週使う魔力点（True なら 3）
            n = 3 if use is True else int(use)
            n = min(n, max(0, h["魔力点"] - 6))  # 急な場面のために 6 点は残す
            h["魔力点"] -= n
            h["xp"]["魔力"] = h["xp"].get("魔力", 0) + n
        prac = rt.get("時繰りの練習", 0)
        if prac and d(20) <= prac // 2 + (1 if st["flags"].get("夜の見張り") else 0) and not (st["flags"].get("練習の隠れ場所") and d(2) == 1) and not (st["flags"].get("竿を移した") and d(2) == 1):
            out.report("時繰りの練習をしているところを、誰かに見られたかもしれない", stop=True)
    h["fatigue"] = round(max(0.0, h["fatigue"] + 0.1 * active - 0.5 - 0.4 * rest), 2)
    if h["fatigue"] >= 3 and not st["flags"].get("病"):
        r = d(6) + d(6) + mod(h["abilities"]["体力"])
        if r < 7:
            st["flags"]["病"] = True
            out.report(f"主人公は無理がたたって寝込んだ（体力判定 2d6={r} < 7）", stop=True)
        else:
            out.report("主人公はひどく疲れている（疲労 3 以上。判定 −2）")


# ---------------------------------------------------------------- 人物・勢力・監視・ランダム
def npcs_week(st, out):
    for name, r in st["npcs"].items():
        nx = r.get("next")
        if not nx or nx.get("week", 10**9) > st["week"]:
            continue
        if nx.get("if") and not cond(st, nx["if"]):
            continue
        out.report(f"〈{name}〉{nx['text']}", stop=nx.get("stop", False), visible=not nx.get("hidden", False),
                   log=not nx.get("hidden", False))
        apply_effects(st, nx.get("effects"), out)
        r["next"] = None
        out.lines.append(f"    → 〈{name}〉の次の一手が未定（GM が人物シートに沿って決め、npc next で登録）")


def watches_week(st, out):
    keep = []
    for wch in st["watches"]:
        if cond(st, wch["if"]):
            out.report(wch["text"], stop=wch.get("stop", True), visible=not wch.get("hidden", False))
            apply_effects(st, wch.get("effects"), out)
            if not wch.get("repeat"):
                continue
        keep.append(wch)
    st["watches"] = keep


def factions_month(st, out):
    y, m, wk = cal(st["week"])
    if wk != 1:
        return
    fdefs = defs("factions")
    for fid, f in st["factions"].items():
        if random.random() > f["野心"] / 30:
            continue
        cd = st.setdefault("action_cd", {})
        cands = [a for a in fdefs[fid]["actions"]
                 if cond(st, a.get("if")) and not (a.get("once") and a["id"] in st["used_actions"])
                 and st["week"] - cd.get(a["id"], -999) >= a.get("cd", 24)]
        if not cands:
            continue
        a = random.choices(cands, weights=[c.get("w", 1) for c in cands])[0]
        if a.get("once"):
            st["used_actions"].append(a["id"])
        cd[a["id"]] = st["week"]
        out.report(f"［{fdefs[fid]['name']}］{a['text']}", stop=a.get("stop", False),
                   visible=a.get("visible", True), log=a.get("visible", True))
        if a.get("ai"):
            append_md(GM_LOG, f"- {cal_str(st['week'])}：（{fdefs[fid]['name']}の打ち返し）{a['ai']}")
        apply_effects(st, a.get("effects"), out)


def events_week(st, out):
    if random.random() > st["domain_extra"].get("イベント率", 0.12):
        return
    evs = defs("events")
    cd = st.setdefault("event_cd", {})
    cands = [e for e in evs if cond(st, e.get("if")) and not (e.get("once") and e["id"] in st["used_events"])
             and st["week"] - cd.get(e["id"], -999) >= e.get("cd", 16)]
    if not cands:
        return
    e = random.choices(cands, weights=[c.get("w", 1) for c in cands])[0]
    if e.get("once"):
        st["used_events"].append(e["id"])
    cd[e["id"]] = st["week"]
    out.report(f"《出来事》{e['text']}", stop=e.get("stop", True), visible=e.get("visible", True))
    apply_effects(st, e.get("effects"), out)


def calendar_week(st, out):
    y, m, wk = cal(st["week"])
    for ev in defs("calendar"):
        if ev.get("month") == m and ev.get("week") == wk and cond(st, ev.get("if")):
            if ev.get("year") and ev["year"] != y:
                continue
            out.report(f"〔暦〕{ev['text']}", stop=ev.get("stop", False), log=ev.get("stop", False))
            apply_effects(st, ev.get("effects"), out)
    bm = st["protagonist"]["born"][1]
    if m == bm and wk == 1:
        out.report(f"主人公は {age(st)} 歳になった", stop=age(st) in (7, 12), log=True)


def rumors_season(st, out):
    y, m, wk = cal(st["week"])
    if not (wk == 4 and m in (2, 5, 8, 11)):
        return
    stages = ["", "館", "領内", "近隣", "辺境伯の城", "王都"]
    for ru in st["rumors"]:
        if ru["stage"] >= 5:
            continue
        r = d(6) + st["domain"]["注目度"] // 20
        if r >= 4:
            ru["stage"] += 1
            twist = d(6) <= 2
            txt = f"噂「{ru['text']}」が{stages[ru['stage']]}まで広がった"
            if twist:
                ru["twisted"] = True
                txt += "（尾ひれがついている）"
            out.report(txt, stop=ru["stage"] >= 4)
            if ru["stage"] >= 4:
                apply_effects(st, {"clocks.異端の目": 1 if ru.get("strange") else 0}, out)


def yearly(st, out):
    y, m, wk = cal(st["week"])
    if (m, wk) != (12, 4):
        return
    apply_effects(st, {"domain.注目度": -5}, out)
    for name, r in st["npcs"].items():
        for k in ("信頼", "好意"):
            v = r.get(k, 0)
            if -3 < v < 4 and v != 0:
                r[k] = v - 1 if v > 0 else v + 1
    out.report("年の終わり：注目度が下がり、強くない感情は少し薄れた")


# ---------------------------------------------------------------- 世界（engine/world.py）
def world_week(st, out):
    """季節の初めに世界を一季節進め、届いた知らせを出し、ハーゼルの数値につなぐ"""
    if st["flags"].get("世界を止める"):
        return
    y, m, wk = cal(st["week"])
    W = WORLD.load()
    new = []
    if (m, wk) in ((3, 1), (6, 1), (9, 1), (12, 1)):
        start = len(W["events"])
        WORLD.season_tick(W)
        W["wk"] = 0
        new = W["events"][start:]
    else:
        W["wk"] = W.get("wk", 0) + 1
    # ハーゼルの側から世界へ：東の休み戦が破れたら、世界でもカルディアと王太子が戦になる
    if st["clocks"].get("東の休み戦", 0) >= 6 and not WORLD.at_war(W, "カルディア", "王太子") and W["polities"]["カルディア"]["alive"]:
        W["wars"].append({"a": "カルディア", "b": "王太子", "since": W["t"], "goal": "地", "score": 0})
    # ハーゼルで仕上がった発明は、世界でも北部の国のものになる
    home_owner = W["regions"][W["home"]]["owner"]
    for pid_, inv in (("風車", "風車"), ("長弓隊", "長弓"), ("竜の粉", "火薬"), ("活版印刷", "活版"), ("蒸留", "蒸留")):
        if pid_ in st["projects_done"] and inv not in W["tech"].get(home_owner, []):
            W["tech"].setdefault(home_owner, []).append(inv)
    # 世界からハーゼルへ
    home = W["home"]
    st["world_harvest"] = W["harvest"].get(home)
    for e in new:
        if e.get("gm"):
            append_md(GM_LOG, f"- {cal_str(st['week'])}：（世界）{e['text']}　〔{e['gm']}〕")
        if e["kind"] == "疫病" and e["region"] == home and ("はやり" in e["text"] or "広がった" in e["text"]):
            apply_effects(st, {"clocks.灰咳の再来": (1 if st["flags"].get("灰咳の封じこめ") else 2) if "灰咳" in e["text"] else 1}, out)
        elif e["kind"] == "疫病" and W["dist"].get(e["region"], 9) == 1 and ("はやり" in e["text"] or "広がった" in e["text"]):
            apply_effects(st, {"clocks.灰咳の再来": 1}, out)
        if e["kind"] == "戦" and "仕掛けた" in e["text"] and "カルディア" in e["text"] and "王太子" in e["text"] and st["clocks"].get("東の休み戦", 0) < 6:
            st["clocks"]["東の休み戦"] = 5
            apply_effects(st, {"clocks.東の休み戦": 1}, out)
        if e["kind"] == "戦" and "迫る勢い" in e["text"] and "摂政" in e["text"]:
            apply_effects(st, {"clocks.摂政軍の北上": 1}, out)
    for n in WORLD.pop_news(W, W["t"] * 12 + W.get("wk", 0)):
        text = n["text"] + ("（尾ひれがついているらしい）" if n["twisted"] else "")
        big = n["mag"] >= 4 or (n["dist"] <= 1 and n["mag"] >= 3)
        out.report(f"［遠い知らせ］{text}", stop=big, log=True)
    WORLD.save(W)


def advance(st, n):
    global CLOCKS
    CLOCKS = defs("clocks")
    for i in range(n):
        st["week"] += 1
        out = Out(st)
        world_week(st, out)
        calendar_week(st, out)
        econ_week(st, out)
        st["_mw"] = lambda w: cal(w)[1:]
        WAR.war_week(st, out, cond, apply_effects, append_md, GM_LOG, cal_str)
        st.pop("_mw", None)
        tick_clocks(st, out)
        factions_month(st, out)
        offices_month(st, out)
        page_month(st, out)
        npcs_week(st, out)
        watches_week(st, out)
        events_week(st, out)
        projects_week(st, out)
        hero_week(st, out)
        rumors_season(st, out)
        yearly(st, out)
        print(f"▼ {cal_str(st['week'])}　主人公 {age(st)} 歳")
        if out.lines:
            print("\n".join(out.lines))
        else:
            print("  ・特に変わったことはない")
        if out.hidden:
            print(f"  （伏せた出来事 {out.hidden} 件 → gm/）")
        save_state(st)
        if out.stops:
            print(f"\n■ ここで止まる：GM は描写と行動決定を。残り {n-i-1} 週は進めていない")
            return
    print()
    brief(st)


# ---------------------------------------------------------------- 表示
def brief(st):
    dm = st["domain"]
    print(f"[{cal_str(st['week'])}] 財貨 {dm['財貨']:.1f} / 負債 {dm['負債']:.0f} / 食糧 {dm['食糧']:.1f} / "
          f"民心 {dm['民心']} / 治安 {dm['治安']} / 人手 {labor_available(st)}人")


def status(st, gm=False):
    global CLOCKS
    CLOCKS = defs("clocks")
    h = st["protagonist"]
    print(f"■ {cal_str(st['week'])}（通算 {st['week']} 週）")
    print(f"■ 主人公 {h['name']}（{age(st)} 歳）　疲労 {h['fatigue']}　小遣い {h['pocket']} 銀貨")
    print("  能力 " + " / ".join(f"{k} {v}({mod(v):+d})" for k, v in h["abilities"].items()))
    print("  週の過ごし方 " + " / ".join(f"{k}{v}日" for k, v in h["routine"].items()))
    if h.get("special"):
        print(f"  特殊能力 {h['special']}　魔力点 {h.get('魔力点')}/{h.get('魔力点上限')}　扱える時間 {TIME_STAGES[min(9, max(1, h['abilities']['魔力'] // 3))]}まで")
    print(f"  系統魔法 {h.get('系統')}（{'洗礼済み' if h.get('洗礼済み') else '洗礼前：人前で使うと野良の疑い'}）")
    if st.get("engagement"):
        print(f"  婚約 {st['engagement']['相手']}（{st['engagement']['条件']}）")
    if st["flags"].get("出仕中"):
        pg = st["page"]
        print(f"■ 出仕 {pg['段階']}　城での評判 {pg['評判']}　派閥の近さ " + " / ".join(f"{k}{v:+d}" for k, v in pg["派閥"].items()))
    dm = st["domain"]
    print("■ 領")
    print("  " + " / ".join(f"{k} {v}" for k, v in dm.items()))
    print(f"  兵 " + " / ".join(f"{k} {v}" for k, v in st["military"].items()) + f"　今週の人手の余力 {labor_available(st)} 人")
    print("■ 方針 " + " / ".join(f"{k}:{v}" for k, v in st.get("policies", {}).items()))
    offs = [f"{k}:{v.get('人') or '空き'}（裁量{v.get('裁量','小')}）" for k, v in st.get("offices", {}).items()]
    print("■ 役職 " + " / ".join(offs) + ("" if st["flags"].get("当主") else "　※当主になるまで委任の判定は動かない"))
    if st.get("treaties"):
        print("■ 取り決め " + " / ".join(f"{t['相手']}と{t['種類']}（{t['条件']}）" for t in st["treaties"]))
    if st.get("war"):
        print(WAR.summary(st, mine_only=not gm))
    print("■ 情勢クロック")
    for cid, c in CLOCKS.items():
        if c.get("retired") or (c.get("only_if") and not cond(st, c["only_if"]) and not gm):
            continue
        if c.get("visible", True) or gm:
            print(f"  {c['name']}：{st['clocks'].get(cid, 0)}/{c['max']}" + ("（隠し）" if not c.get('visible', True) else ""))
    pdefs = defs("projects")
    if st["projects_active"]:
        print("■ 進行中の計画")
        for p in st["projects_active"]:
            pd = pdefs[p["id"]]
            print(f"  {pd['name']}：労働 {p['labor']}/{pd.get('labor',0)} 人週、{p['weeks']}/{pd.get('min_weeks',1)} 週、投入 {p['people']} 人")
    if st["projects_done"]:
        print("■ 完成した計画：" + "、".join(pdefs[i]["name"] for i in st["projects_done"]))
    print("■ 人物との関係")
    for name, r in st["npcs"].items():
        nx = r.get("next")
        nxs = ""
        if gm and nx:
            nxs = f"　次の一手：{cal_str(nx['week'])}「{nx['text']}」"
        print(f"  {name}：信頼 {r['信頼']:+d} 好意 {r['好意']:+d} 警戒 {r['警戒']} 借り {r.get('借り',0):+d}{nxs}")
        if r.get("印象"):
            print(f"      印象：{r['印象']}")
    print("■ 勢力")
    fdefs = defs("factions")
    for fid, f in st["factions"].items():
        if fdefs[fid].get("hidden") and not gm and not st["flags"].get(f"知った_{fid}"):
            continue
        print(f"  {fdefs[fid]['name']}：態度 {f['態度']:+d}　" + " ".join(f"{k}{v}" for k, v in f.items() if k not in ('態度',)))
    if gm and st.get("rel"):
        print("■ 勢力どうしの関係（GM）　" + " / ".join(f"{k} {v:+d}" for k, v in st["rel"].items()))
    if st["rumors"]:
        print("■ 噂")
        for ru in st["rumors"]:
            print(f"  [{ru['stage']}] {ru['text']}" + ("（尾ひれつき）" if ru.get("twisted") else ""))


# ---------------------------------------------------------------- 判定
def check(st, ability, dc, bonus=0, note="", calm=False):
    h = st["protagonist"]
    v = h["abilities"].get(ability)
    if v is None:
        raise SystemExit(f"能力がありません: {ability}")
    pen = fatigue_pen(h["fatigue"])
    if calm:
        total = 7 + mod(v) + bonus + pen
        res = "成功" if total >= dc else "失敗（落ち着いて取り組んでも届かない。振るか、別の手を）"
        print(f"🎲 {ability}判定{('（'+note+'）') if note else ''}：落ち着いて取り組む 7 {mod(v):+d}{(' %+d' % bonus) if bonus else ''}{(' 疲労%d' % pen) if pen else ''} ＝ {total} vs {dc} → {res}")
        return res
    a1, a2, r = roll2d6()
    total = r + mod(v) + bonus + pen
    res = grade(r, total, dc)
    res = {"代償つき": "惜しい失敗（代償つき成功も可）"}.get(res, res)
    extra = f" {bonus:+d}" if bonus else ""
    extra += f" 疲労{pen}" if pen else ""
    print(f"🎲 {ability}判定{('（'+note+'）') if note else ''}：2d6[{a1},{a2}]={r} {mod(v):+d}{extra} ＝ {total} vs {dc} → {res}")
    gain_xp(st, ability, res)
    return res


def persuade(st, name, dc, match=0, loss=0, status_=None, proof=False, bonus=0):
    """説得（2d6）。match: 利益の合致 +1/+2/+3、loss: 相手の損 1/3、dc: 小6/普8/大10/人生12"""
    r_ = st["npcs"].get(name)
    if r_ is None:
        raise SystemExit(f"人物がいません: {name}")
    h = st["protagonist"]
    if status_ is None:
        status_ = (-1 if r_["信頼"] < 3 else 0) if age(st) < 12 else 0
    cards = h.get("cards", {})
    psych = 1 if cards.get("説得と交渉の心理", 0) >= 1 else 0
    proof_v = (3 if cards.get("統計と実験計画", 0) >= 1 else 2) if proof else 0
    half = lambda x: int(x / 2)
    a1, a2, r = roll2d6()
    parts = [("出目", r), ("弁舌", mod(h["abilities"]["弁舌"])), ("信頼", half(r_["信頼"])), ("好意", int(r_["好意"] / 3)),
             ("警戒", -half(r_["警戒"] + 1) if r_["警戒"] else 0), ("利益の合致", match), ("相手の損", -loss), ("立場", status_),
             ("実証", proof_v), ("心理学", psych), ("その他", bonus)]
    if fatigue_pen(h["fatigue"]):
        parts.append(("疲労", fatigue_pen(h["fatigue"])))
    total = sum(v for _, v in parts)
    margin = total - dc
    if r == 2:
        res = "反発：相手は自分のやり方で対抗する（告げ口・妨害など）。警戒 +1"
        r_["警戒"] = min(5, r_["警戒"] + 1)
    elif margin >= 0 or r == 12:
        res = "成功：承諾。ただし相手は自分の条件をつけてよい" + ("（大成功）" if r == 12 else "")
    elif margin >= -2:
        res = "保留・条件付き：相手が対価や条件を示す"
    else:
        res = "拒否：警戒 +1"
        r_["警戒"] = min(5, r_["警戒"] + 1)
    shown = " ".join(f"{k}{v:+d}" for k, v in parts if v and k != "出目")
    print(f"🗣 {name}への説得：2d6[{a1},{a2}]={r} {shown} ＝ {total} vs {dc} → {res}")
    if res.startswith("成功"):
        gain_xp(st, "弁舌", "大成功" if r == 12 else "成功")
    save_state(st)


def react(who, base, factors, note=""):
    """人物・勢力の反応判定。2d6 ＋ 態度 ＋ 要因（軽い±1／ふつう±2／決定的±3）。合計の傾きが ±5 を超えたら振らない"""
    fs = []
    for f in factors:
        name, _, val = f.rpartition(":")
        fs.append((name, int(val)))
    lean = base + sum(v for _, v in fs)
    shown = f"態度{base:+d} " + " ".join(f"{n}{v:+d}" for n, v in fs)
    def label(t):
        return "とてもよい" if t >= 12 else "よい" if t >= 9 else "ふつう" if t >= 6 else "悪い" if t >= 3 else "とても悪い"
    if abs(lean) > 5:
        total = 7 + lean
        print(f"⚖ {who}の反応{('（'+note+'）') if note else ''}：{shown} ＝ 傾き{lean:+d} → 傾きが大きいので振らない（7{lean:+d}＝{total}）→ 【{label(total)}】")
        return
    a1, a2, r = roll2d6()
    total = r + lean
    print(f"⚖ {who}の反応{('（'+note+'）') if note else ''}：2d6[{a1},{a2}]={r} {shown} ＝ {total} → 【{label(total)}】（5以下 悪い／6〜8 ふつう／9〜11 よい／12〜 とてもよい）")


# ---------------------------------------------------------------- 方針（政策）
def policy_effects(st):
    pdefs = defs("policies")
    res = {"tax": 1.0, "demesne": 1.0, "labor": 1.0, "winter": 1.0, "monthly": [], "clock": {}}
    for k, v in st.get("policies", {}).items():
        o = pdefs.get(k, {}).get(v, {})
        for f in ("tax", "demesne", "labor", "winter"):
            res[f] *= o.get(f, 1.0)
        if o.get("monthly"):
            res["monthly"].append(o["monthly"])
        for c, p in o.get("clock", {}).items():
            res["clock"][c] = res["clock"].get(c, 0) + p
    return res


# ---------------------------------------------------------------- 家臣への委任
OFFICES = {
    "家令": {"stat": "実務", "good": {"domain.財貨": 2}, "bad": {"domain.財貨": -2}, "text": "財政と年貢の取り立て"},
    "騎士隊長": {"stat": "武勇", "good": {"domain.治安": 2}, "bad": {"domain.治安": -1}, "text": "兵と治安"},
    "教えと衛生": {"stat": "実務", "good": {"domain.衛生": 1}, "bad": {}, "text": "教会・読み書き・衛生"},
    "外交": {"stat": "交渉", "good": {}, "bad": {}, "text": "使者・交渉（交渉の判定に 交渉÷3 を足す）"},
    "代官": {"stat": "実務", "good": {"domain.民心": 1, "domain.財貨": 1}, "bad": {"domain.民心": -1}, "text": "主人公が留守のあいだ領を預かる"},
}


def loyalty(st, name):
    r = st["npcs"].get(name)
    if r:
        return r.get("信頼", 0)
    return st["vassals"].get(name, {}).get("忠誠", 0)


def offices_month(st, out):
    y, m, wk = cal(st["week"])
    if wk != 1 or not (st["flags"].get("当主") or st["flags"].get("代官を置く")):
        return
    for office, o in st.get("offices", {}).items():
        who = o.get("人")
        if not who:
            continue
        od = OFFICES[office]
        v = st["vassals"].get(who, {})
        r = d(10) + v.get(od["stat"], 5)
        grade = "好成績" if r >= 14 else ("不手際" if r <= 8 else "並")
        eff = od["good"] if grade == "好成績" else (od["bad"] if grade == "不手際" else {})
        if grade != "並" and eff:
            out.report(f"〈{office}・{who}〉{od['text']}：{grade}（🎲{r}）。{v.get('癖', '')}")
            apply_effects(st, eff, out)
        lo, amb = loyalty(st, who), v.get("野心", 3)
        if lo <= 0 and amb >= 6 and d(6) == 1:
            out.report(f"〈{office}・{who}〉が預かった金の一部を懐に入れた", visible=False)
            apply_effects(st, {"domain.財貨": -3}, out)
        if o.get("裁量") == "大" and amb >= 5 and d(10) == 1:
            out.report(f"〈{office}・{who}〉が主人公に諮らず、自分の判断で事を進めた（方針：{o.get('方針', 'なし')}）。GM が性格に沿って中身を決める", stop=True)


# ---------------------------------------------------------------- 出仕（少年期）
def page_month(st, out):
    y, m, wk = cal(st["week"])
    if not st["flags"].get("出仕中"):
        return
    pg = st["page"]
    need = 3 if pg.get("段階") == "小姓" else 2
    if st["flags"].get("帰郷中") or st["flags"].get("旅の途中"):
        return  # 冬の帰郷のあいだは、務めはない
    if st["protagonist"]["routine"].get("務め", 0) < need:
        apply_effects(st, {"page.評判": -1}, out)
        out.report(f"務めの日数が足りない（{pg.get('段階')}は週 {need} 日）。城での評判 −1")
    if wk != 2:
        return
    used = pg.setdefault("使った務め", {})
    tasks = [t for t in defs("page_tasks") if cond(st, t.get("if")) and st["week"] - used.get(t["id"], -999) >= t.get("cd", 36)
             and not (t.get("once") and t["id"] in used)]
    if not tasks:
        return  # 出せる務めがない週は、何も起きない（同じ務めを繰り返さない）
    t = random.choices(tasks, weights=[x.get("w", 1) for x in tasks])[0]
    used[t["id"]] = st["week"]
    pg["今の務め"] = t["id"]
    ch = f"　※{t['choice']}" if t.get("choice") else ""
    out.report(f"〔務め〕{t['text']}（{t['ability']}判定 目標 {t['dc']}。結果は page resolve 成功|失敗）{ch}", stop=True)


def page_resolve(st, result):
    pg = st["page"]
    t = next((x for x in defs("page_tasks") if x["id"] == pg.get("今の務め")), None)
    if not t:
        raise SystemExit("いま解決待ちの務めはない")
    eff = t["success"] if result in ("成功", "大成功") else t["fail"]
    out = Out(st)
    apply_effects(st, eff, out)
    pg["今の務め"] = None
    save_state(st)
    print(f"務め「{t['id']}」：{result} → {eff}　城での評判 {pg['評判']}　派閥 {pg['派閥']}")


# ---------------------------------------------------------------- 外交：裁き・取り決め・縁談
def court(st, ours, theirs, our_mod=None, their_mod=0, our_voice=0, their_voice=0, their_favor=0):
    h = st["protagonist"]
    if our_mod is None:
        our_mod = mod(h["abilities"]["弁舌"])
    favor = (st["domain"]["主家の覚え"] - 50) // 10
    r1, r2 = d(6) + d(6), d(6) + d(6)
    favor = (st["domain"]["主家の覚え"] - 50) // 20
    a = r1 + ours + our_mod + favor + our_voice
    b = r2 + theirs + their_mod + their_favor + their_voice
    diff = a - b
    if diff >= 3:
        res = "勝訴：こちらの言い分が通る"
    elif diff >= 1:
        res = "有利な痛み分け：こちらに有利な形で分け合う"
    elif diff >= -2:
        res = "不利な痛み分け：相手に有利な形で分け合う"
    else:
        res = "敗訴：相手の言い分が通る"
    print(f"⚖ 裁き：こちら 2d6={r1} 証拠{ours} 弁論{our_mod:+d} 主家の覚え{favor:+d} 口添え{our_voice} ＝ {a}"
          f" ／ 相手 2d6={r2} 証拠{theirs} 弁論{their_mod:+d} 覚え{their_favor:+d} 口添え{their_voice} ＝ {b}")
    print(f"  差 {diff:+d} → 【{res}】")
    print("  ※負けた側の勢力の態度 −2。決闘裁判を申し出ることもできる（騎士どうし・武芸の戦い）")


# ---------------------------------------------------------------- 系統魔法
TIER_REQ = {1: 0, 2: 9, 3: 13, 4: 16, 5: 20, 6: 24}


def magic(st, spell, witnesses=0, bonus=0, note=""):
    h = st["protagonist"]
    school = h.get("系統")
    sp = defs("spells").get(school, {}).get(spell)
    if not sp:
        raise SystemExit(f"{school}の呪文：{'、'.join(defs('spells').get(school, {}))}")
    mg = h["abilities"]["魔力"]
    if mg < TIER_REQ[sp["tier"]]:
        raise SystemExit(f"「{spell}」には魔力 {TIER_REQ[sp['tier']]} が要る（今 {mg}）")
    dc = sp["dc"]
    mastery = min(3, max(0, (mg - TIER_REQ[sp["tier"]]) // 3))  # 呪文の熟達（821年 草月）
    cost = max(1, sp["cost"] - mastery)
    if h["魔力点"] < cost:
        raise SystemExit(f"魔力点が足りない（必要 {cost}、残り {h['魔力点']}）")
    pen = fatigue_pen(h["fatigue"])
    a1, a2, r = roll2d6()
    total = r + mod(mg) + bonus + pen
    h["魔力点"] -= cost
    h["xp"]["魔力"] = h["xp"].get("魔力", 0) + sp["tier"] * 2
    res = grade(r, total, dc)
    print(f"✦ {school}「{spell}」{('（'+note+'）') if note else ''}：2d6[{a1},{a2}]={r} {mod(mg):+d}{(' %+d' % bonus) if bonus else ''}{(' 疲労%d' % pen) if pen else ''} ＝ {total} vs {dc} → {res}　魔力点 −{cost}（残り {h['魔力点']}/{h['魔力点上限']}）" + (f"　熟達 {mastery}" if mastery else ""))
    if res in ("成功", "大成功", "代償つき"):
        print(f"  効果：{sp['effect']}" + ("（ぼんやりとしか見えない）" if res == "代償つき" else ""))
        for i, mt in enumerate(sp.get("熟達", [])[:mastery], 1):
            print(f"  熟達 {i}：{mt}")
    elif res == "大失敗":
        h["fatigue"] += 1
        print("  反動：見えたものは偽りか、見えすぎて頭が割れるように痛む（疲労 +1。GM が誤った情報を一つ与えてもよい）")
    else:
        if dc - total >= 3:
            h["fatigue"] += 0.5
            print("  何も見えなかった。大きく外した反動で疲労 +0.5")
        else:
            print("  何も見えなかった（反動なし）")
    if witnesses and res != "失敗":
        if not h.get("洗礼済み"):
            st["clocks"]["異端の目"] = min(8, st["clocks"]["異端の目"] + 1)
            st["domain"]["注目度"] = min(100, st["domain"]["注目度"] + witnesses)
            print(f"  ！ 洗礼前の力を {witnesses} 人に見られた（野良の疑い）：異端の目 +1、注目度 +{witnesses}")
        else:
            st["domain"]["注目度"] = min(100, st["domain"]["注目度"] + witnesses)
            print(f"  ・ {witnesses} 人が見ていた：注目度 +{witnesses}（見識持ちは教会が囲い込みたがる）")
    save_state(st)


# ---------------------------------------------------------------- 時繰り（主人公の固有魔法）
TIME_STAGES = {1: "数分", 2: "数時間", 3: "数日", 4: "数か月", 5: "数年", 6: "数十年", 7: "百年", 8: "数百年", 9: "千年"}
SIZES = {"小物": 1, "人": 2, "道具": 2, "動物": 2, "荷車": 4, "小屋": 4, "家": 8, "畑": 8}


def jikuri(st, direction, stage, size, living=False, witnesses=0, bonus=0, note=""):
    h = st["protagonist"]
    mg = h["abilities"]["魔力"]
    max_stage = min(9, max(1, mg // 3))
    if stage > max_stage:
        raise SystemExit(f"今の魔力 {mg} で扱えるのは {TIME_STAGES[max_stage]}（段階 {max_stage}）まで")
    if size not in SIZES:
        raise SystemExit(f"大きさは {'・'.join(SIZES)} のどれか")
    cost = stage * SIZES[size] * (2 if living else 1)
    j_mastery = min(3, max(0, (mg - stage * 3) // 3))  # 時繰りの熟達：段階に要る魔力を 3 上回るごとに費用 −2 割
    cost = max(1, math.ceil(cost * (1 - 0.2 * j_mastery)))
    if h["魔力点"] < cost:
        raise SystemExit(f"魔力点が足りない（必要 {cost}、残り {h['魔力点']}）")
    dc = 5 + stage + (1 if living else 0) + (1 if SIZES[size] >= 4 else 0)
    pen = fatigue_pen(h["fatigue"])
    a1, a2, r = roll2d6()
    total = r + mod(mg) + bonus + pen
    h["魔力点"] -= cost
    lines = [f"⏳ 時繰り（{direction}・{TIME_STAGES[stage]}・{size}{'・生き物' if living else ''}{('・'+note) if note else ''}）："
             f"2d6[{a1},{a2}]={r} {mod(mg):+d}{(' %+d' % bonus) if bonus else ''}{(' 疲労%d' % pen) if pen else ''} ＝ {total} vs {dc}　魔力点 −{cost}（残り {h['魔力点']}/{h['魔力点上限']}）"]
    if r == 2:
        res = "大失敗"
        r2 = d(6)
        recoil = {1: "自分の数時間分の記憶が抜け落ちた", 2: "髪がひと筋、白くなった", 3: "鼻血が止まらず、二日寝込んだ（疲労 +2）",
                  4: "体の時間がずれ、数日ぶん痩せた（体力の経験を失う）", 5: "周りの物まで時間がゆがんだ。誰かに見られたかもしれない",
                  6: "黒の森の方角で、何かがこちらを向いた気がした"}[r2]
        lines.append(f"  → 大失敗。反動：{recoil}")
        h["fatigue"] += 2 if r2 == 3 else 1
        if r2 == 4:
            h["xp"]["体力"] = 0
        if r2 == 5:
            witnesses = max(witnesses, 1)
        if r2 == 6:
            st["clocks"]["黒の森の異変"] = min(8, st["clocks"]["黒の森の異変"] + 1)
            append_md(GM_LOG, f"- {cal_str(st['week'])}：時繰りの大失敗。森の主（と遺跡）が主人公に気づいた")
    elif total >= dc or r == 12:
        res = "大成功" if r == 12 else "成功"
        lines.append(f"  → {res}。時は思いどおりに動いた" + ("（魔力点を半分取り戻した）" if r == 12 else ""))
        if r == 12:
            h["魔力点"] = min(h["魔力点上限"], h["魔力点"] + cost // 2)
    elif total >= dc - 1:
        res = "代償つき"
        lines.append("  → 半ばの成功。望んだ半分だけ時が動いた（反動なし）")
    else:
        res = "失敗"
        if dc - total >= 3:
            h["fatigue"] += 0.5
            lines.append("  → 失敗。時は動かず、大きく外した反動で疲労 +0.5")
        else:
            lines.append("  → 失敗。時は動かなかった（反動なし）")
    # 経験
    h["xp"]["魔力"] = h["xp"].get("魔力", 0) + stage * 2
    # 目撃
    if witnesses > 0 and res != "失敗":
        att = 2 * witnesses + 2 * stage
        st["domain"]["注目度"] = min(100, st["domain"]["注目度"] + att)
        st["clocks"]["異端の目"] = min(8, st["clocks"]["異端の目"] + 1)
        lines.append(f"  ！ {witnesses} 人に見られた：注目度 +{att}、異端の目 +1（GM は見た人物の印象と警戒を更新し、噂を足すこと）")
    print("\n".join(lines))
    save_state(st)


# ---------------------------------------------------------------- 戦闘
def battle(st, a, b, terrain="平地", a_lead=0, b_lead=0, named=None):
    units = defs("units")

    def strength(side, defend=False):
        s = 0
        for u, n in side.items():
            ud = units.get(u)
            if not ud:
                raise SystemExit(f"兵種がありません: {u}（engine/data/units.json）")
            k = ud.get("terrain", {}).get(terrain, 1.0)
            base_str = ud["str"]
            if u in ("訓練された民兵", "槍衾兵", "長弓兵") and st["flags"].get("民兵の鎧"):
                base_str += 0.5  # 民兵の鎧と盾
            s += base_str * n * k
        return s

    ra, rb = d(6) + d(6), d(6) + d(6)
    fl = st["flags"]
    # 味方（a）はハーゼルとする。戦の計画の効き目
    bonus = (1 if fl.get("号令") else 0) + (2 if fl.get("火薬") else 0)
    if bonus:
        print(f"  （戦の計画の効き目：判定 +{bonus}　" + "・".join(x for x, f in (("規律と号令", "号令"), ("竜の粉", "火薬")) if fl.get(f)) + "）")
    a_lead += bonus
    sa = strength(a) * (1 + (ra + a_lead - 7) / 10)
    sb = strength(b) * (1 + (rb + b_lead - 7) / 10)
    if terrain == "防御":
        sa *= 2.5 if fl.get("多重の守り") else 2.0
    elif terrain == "平地" and fl.get("荷車の砦"):
        sa *= 1.5
    ratio = sa / max(sb, 0.01)
    table = [(2.0, "大勝", 0.05, 0.5, 0), (1.25, "勝ち", 0.1, 0.3, 1), (0.8, "拮抗", 0.2, 0.2, 2),
             (0.5, "負け", 0.3, 0.1, 4), (0, "大敗", 0.5, 0.05, 7)]
    for th, res, la, lb, risk in table:
        if ratio >= th:
            break
    if fl.get("野戦の手当て"):
        la = round(la * 0.7, 3)
        risk = max(0, risk - 1)
    print(f"⚔ 戦い（{terrain}）：味方 戦力{strength(a):.1f} 🎲{ra}{a_lead:+d} → {sa:.1f} ／ 敵 戦力{strength(b):.1f} 🎲{rb}{b_lead:+d} → {sb:.1f}")
    print(f"  比 {ratio:.2f} → 【{res}】 味方の損害 約{int(la*100)}% ／ 敵の損害 約{int(lb*100)}%")
    for u, n in a.items():
        print(f"    味方 {u}：{n} → 失う {round(n*la)}")
    for u, n in b.items():
        print(f"    敵 {u}：{n} → 失う {round(n*lb)}")
    for nm in (named or []):
        r = d(20)
        if r <= risk:
            r2 = d(20)
            can_die = res in ("負け", "大敗")
            fate = "戦死" if (can_die and r2 <= 2) else "重傷" if r2 <= 9 else "軽傷"
            print(f"  ✚ {nm}：🎲{r} ≦ {risk} → {fate}（🎲{r2}）")
        else:
            print(f"  ✚ {nm}：無事（🎲{r} > {risk}）")


# ---------------------------------------------------------------- メイン
def parse_value(s):
    if s in ("true", "false"):
        return s == "true"
    if s in ("null", "none"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def main():
    random.seed()
    ap = argparse.ArgumentParser(description="ハーゼル領記エンジン")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--gm", action="store_true")
    s = sub.add_parser("advance"); s.add_argument("n", nargs="?", type=int, default=1)
    s = sub.add_parser("check"); s.add_argument("ability"); s.add_argument("dc", type=int)
    s.add_argument("--bonus", type=int, default=0); s.add_argument("--note", default="")
    s.add_argument("--calm", action="store_true", help="落ち着いて取り組める場面。振らずに 7＋修正")
    s = sub.add_parser("react"); s.add_argument("who"); s.add_argument("--base", type=int, default=0)
    s.add_argument("--factor", action="append", default=[], help="要因:値（例 山の民との約束:-3）"); s.add_argument("--note", default="")
    s = sub.add_parser("persuade"); s.add_argument("name"); s.add_argument("--dc", type=int, required=True)
    s.add_argument("--match", type=int, default=0); s.add_argument("--loss", type=int, default=0)
    s.add_argument("--status", type=int, default=None); s.add_argument("--proof", action="store_true")
    s.add_argument("--bonus", type=int, default=0)
    s = sub.add_parser("roll"); s.add_argument("expr")
    s = sub.add_parser("adj"); s.add_argument("path"); s.add_argument("delta", type=float); s.add_argument("reason")
    s = sub.add_parser("set"); s.add_argument("path"); s.add_argument("value"); s.add_argument("reason")
    s = sub.add_parser("routine"); s.add_argument("items", nargs="+")
    s = sub.add_parser("project"); s.add_argument("action"); s.add_argument("args", nargs="*")
    s = sub.add_parser("npc"); s.add_argument("action"); s.add_argument("name"); s.add_argument("weeks", type=int)
    s.add_argument("text"); s.add_argument("--stop", action="store_true"); s.add_argument("--hidden", action="store_true")
    s.add_argument("--effects", default="{}"); s.add_argument("--if", dest="cond", default=None)
    s = sub.add_parser("watch"); s.add_argument("action"); s.add_argument("expr"); s.add_argument("text")
    s.add_argument("--stop", action="store_true"); s.add_argument("--hidden", action="store_true")
    s.add_argument("--effects", default="{}"); s.add_argument("--repeat", action="store_true")
    s = sub.add_parser("rumor"); s.add_argument("action"); s.add_argument("text", nargs="?"); s.add_argument("stage", nargs="?", type=int, default=1)
    s.add_argument("--strange", action="store_true")
    s = sub.add_parser("battle"); s.add_argument("--a", required=True); s.add_argument("--b", required=True)
    s.add_argument("--terrain", default="平地"); s.add_argument("--a-lead", type=int, default=0)
    s.add_argument("--b-lead", type=int, default=0); s.add_argument("--named", default="")
    s = sub.add_parser("jikuri"); s.add_argument("direction", choices=["戻す", "進める"]); s.add_argument("--stage", type=int, default=1)
    s.add_argument("--size", default="小物"); s.add_argument("--living", action="store_true"); s.add_argument("--witness", type=int, default=0)
    s.add_argument("--bonus", type=int, default=0); s.add_argument("--note", default="")
    s = sub.add_parser("magic"); s.add_argument("spell"); s.add_argument("--witness", type=int, default=0)
    s.add_argument("--bonus", type=int, default=0); s.add_argument("--note", default="")
    s = sub.add_parser("policy"); s.add_argument("action"); s.add_argument("key", nargs="?"); s.add_argument("value", nargs="?")
    s.add_argument("reason", nargs="?", default="")
    s = sub.add_parser("appoint"); s.add_argument("office"); s.add_argument("who"); s.add_argument("--discretion", default="小")
    s.add_argument("--policy", default="")
    s = sub.add_parser("page"); s.add_argument("action"); s.add_argument("arg", nargs="?")
    s = sub.add_parser("court"); s.add_argument("--ours", type=int, required=True); s.add_argument("--theirs", type=int, required=True)
    s.add_argument("--our-mod", type=int, default=None); s.add_argument("--their-mod", type=int, default=0)
    s.add_argument("--our-voice", type=int, default=0); s.add_argument("--their-voice", type=int, default=0)
    s.add_argument("--their-favor", type=int, default=0)
    s = sub.add_parser("treaty"); s.add_argument("action"); s.add_argument("partner", nargs="?"); s.add_argument("kind", nargs="?")
    s.add_argument("terms", nargs="?", default="")
    s = sub.add_parser("marriage"); s.add_argument("action"); s.add_argument("name", nargs="?"); s.add_argument("terms", nargs="?", default="")
    s = sub.add_parser("rewind"); s.add_argument("action", choices=["list", "to", "status"]); s.add_argument("n", nargs="?", type=int)
    s.add_argument("reason", nargs="?", default="")
    s = sub.add_parser("impression"); s.add_argument("name"); s.add_argument("text")
    s = sub.add_parser("log"); s.add_argument("text")
    sub.add_parser("init")
    a = ap.parse_args()

    global CLOCKS
    CLOCKS = defs("clocks")
    if a.cmd == "init":
        st = load_json(INIT)
        save_state(st)
        print("初期状態に戻しました")
        return
    if a.cmd in ("advance", "check", "persuade", "magic", "jikuri", "battle", "court", "roll", "adj", "set", "project", "react"):
        snapshot(f"{a.cmd} " + " ".join(str(v) for k, v in vars(a).items() if k not in ("cmd",) and v not in (None, "", 0, False, [], "{}"))[:60])
    st = load_state()

    if a.cmd == "status":
        status(st, a.gm)
    elif a.cmd == "advance":
        advance(st, a.n)
    elif a.cmd == "check":
        check(st, a.ability, a.dc, a.bonus, a.note, a.calm)
    elif a.cmd == "react":
        react(a.who, a.base, a.factor, a.note)
    elif a.cmd == "persuade":
        persuade(st, a.name, a.dc, a.match, a.loss, a.status, a.proof, a.bonus)
    elif a.cmd == "roll":
        rs, tot = roll_expr(a.expr)
        print(f"🎲 {a.expr}：{rs} → {tot}")
    elif a.cmd == "adj":
        old = get_path(st, a.path)
        delta = int(a.delta) if a.delta == int(a.delta) and isinstance(old, int) else a.delta
        out = Out(st)
        apply_effects(st, {a.path: delta}, out)
        new = get_path(st, a.path)
        print(f"{a.path}：{old} → {new}（{a.reason}）")
        if out.lines:
            print("\n".join(out.lines))
        if a.path.startswith("npcs."):
            parts = a.path.split(".")
            st["npcs"][parts[1]].setdefault("history", []).append(f"{cal_str(st['week'])}：{parts[2]} {old}→{new}（{a.reason}）")
        save_state(st)
    elif a.cmd == "set":
        v = parse_value(a.value)
        set_path(st, a.path, v)
        print(f"{a.path} ＝ {v}（{a.reason}）")
        save_state(st)
    elif a.cmd == "routine":
        rt = {}
        for it in a.items:
            k, v = it.split("=")
            rt[k] = int(v)
        if sum(rt.values()) > 6:
            raise SystemExit("1 週は 6 日まで（聖日は休み）")
        acts = defs("activities")
        for k in rt:
            if k not in acts:
                raise SystemExit(f"過ごし方がありません: {k}（候補：{'、'.join(acts)}）")
        st["protagonist"]["routine"] = rt
        save_state(st)
        print("週の過ごし方：" + " / ".join(f"{k}{v}日" for k, v in rt.items()))
    elif a.cmd == "project":
        project_cmd(st, a.action, a.args)
    elif a.cmd == "npc":
        if a.name not in st["npcs"]:
            st["npcs"][a.name] = {"信頼": 0, "好意": 0, "警戒": 0, "借り": 0, "next": None}
        st["npcs"][a.name]["next"] = {"week": st["week"] + a.weeks, "text": a.text, "stop": a.stop,
                                       "hidden": a.hidden, "effects": json.loads(a.effects), "if": a.cond}
        save_state(st)
        print(f"〈{a.name}〉次の一手：{cal_str(st['week'] + a.weeks)}「{a.text}」")
    elif a.cmd == "watch":
        st["watches"].append({"if": a.expr, "text": a.text, "stop": a.stop, "hidden": a.hidden,
                              "effects": json.loads(a.effects), "repeat": a.repeat})
        save_state(st)
        print(f"監視を追加：{a.expr} → {a.text}")
    elif a.cmd == "rumor":
        if a.action == "add":
            st["rumors"].append({"text": a.text, "stage": a.stage, "strange": a.strange, "week": st["week"]})
            save_state(st)
            print(f"噂を追加：[{a.stage}] {a.text}")
        else:
            for ru in st["rumors"]:
                print(f"[{ru['stage']}] {ru['text']}")
    elif a.cmd == "battle":
        battle(st, json.loads(a.a), json.loads(a.b), a.terrain, a.a_lead, a.b_lead,
               [x for x in a.named.split(",") if x])
    elif a.cmd == "jikuri":
        jikuri(st, a.direction, a.stage, a.size, a.living, a.witness, a.bonus, a.note)
    elif a.cmd == "magic":
        magic(st, a.spell, a.witness, a.bonus, a.note)
    elif a.cmd == "policy":
        pdefs = defs("policies")
        if a.action == "show":
            for k, opts in pdefs.items():
                if k.startswith("_"):
                    continue
                cur = st["policies"].get(k)
                print(f"■ {k}（今：{cur}）")
                for o, v in opts.items():
                    print(f"   {'▶' if o == cur else ' '} {o}：{v.get('text', '')}")
        elif a.action == "set":
            if a.value not in pdefs.get(a.key, {}):
                raise SystemExit(f"{a.key} の選択肢：{'、'.join(pdefs.get(a.key, {}))}")
            old = st["policies"].get(a.key)
            st["policies"][a.key] = a.value
            out = Out(st)
            for f, dv in pdefs[a.key][a.value].get("faction", {}).items():
                apply_effects(st, {f"factions.{f}.態度": dv}, out)
            append_md(LOG_MD, f"- {cal_str(st['week'])}：方針「{a.key}」を {old} → {a.value} に（{a.reason}）")
            save_state(st)
            print(f"方針「{a.key}」：{old} → {a.value}")
    elif a.cmd == "appoint":
        if a.office not in OFFICES:
            raise SystemExit(f"役職：{'、'.join(OFFICES)}")
        st["offices"][a.office] = {"人": None if a.who in ("なし", "空き") else a.who, "裁量": a.discretion, "方針": a.policy}
        if a.who not in st["vassals"] and a.who not in ("なし", "空き"):
            st["vassals"][a.who] = {"実務": 5, "武勇": 5, "交渉": 5, "野心": 3, "忠誠": 0, "癖": ""}
            print(f"（{a.who} の家臣としての能力は仮に 5。set vassals.{a.who}.実務 7 などで決める）")
        save_state(st)
        append_md(LOG_MD, f"- {cal_str(st['week'])}：{a.office}に {a.who} を任じた（裁量 {a.discretion}、方針：{a.policy or 'なし'}）")
        print(f"{a.office}：{a.who}（裁量 {a.discretion}）方針：{a.policy or 'なし'}")
    elif a.cmd == "page":
        if a.action == "start":
            st["flags"]["出仕中"] = True
            st["page"]["段階"] = a.arg or "小姓"
            save_state(st)
            print(f"出仕を始めた：{st['page']['段階']}。routine に「務め」を週 {3 if st['page']['段階']=='小姓' else 2} 日以上入れること")
        elif a.action == "resolve":
            page_resolve(st, a.arg)
        elif a.action == "end":
            st["flags"]["出仕中"] = False
            save_state(st)
            print("出仕を終えた")
    elif a.cmd == "court":
        court(st, a.ours, a.theirs, a.our_mod, a.their_mod, a.our_voice, a.their_voice, a.their_favor)
    elif a.cmd == "treaty":
        if a.action == "add":
            st["treaties"].append({"相手": a.partner, "種類": a.kind, "条件": a.terms, "週": st["week"]})
            append_md(LOG_MD, f"- {cal_str(st['week'])}：{a.partner}と{a.kind}を結んだ（{a.terms}）")
            save_state(st)
            print(f"取り決め：{a.partner}と{a.kind}（{a.terms}）")
        elif a.action == "break":
            st["treaties"] = [t for t in st["treaties"] if not (t["相手"] == a.partner and t["種類"] == a.kind)]
            out = Out(st)
            apply_effects(st, {"domain.名誉": -10}, out)
            if a.partner in st["factions"]:
                apply_effects(st, {f"factions.{a.partner}.態度": -3}, out)
            for f in st["factions"]:
                if f != a.partner:
                    apply_effects(st, {f"factions.{f}.態度": -1 if d(6) <= 2 else 0}, out)
            append_md(LOG_MD, f"- {cal_str(st['week'])}：{a.partner}との{a.kind}を破った（{a.terms}）")
            save_state(st)
            print(f"{a.partner}との{a.kind}を破った：名誉 −10、{a.partner}の態度 −3、ほかの勢力も信用を落とすことがある")
        else:
            for t in st["treaties"]:
                print(f"{t['相手']}：{t['種類']}（{t['条件']}）")
    elif a.cmd == "marriage":
        if a.action == "list":
            for n, c in defs("marriage").items():
                if n.startswith("_"):
                    continue
                print(f"■ {n}（{cal(st['week'])[0]-c['born']}歳・{c['house']}・{c['rank']}）持参金 {c['dowry']}")
                print(f"   効果：{c['effect']}\n   求められそうなこと：{c['ask']}\n   人柄の噂：{c['人柄']}")
        elif a.action == "engage":
            st["engagement"] = {"相手": a.name, "条件": a.terms, "週": st["week"]}
            append_md(LOG_MD, f"- {cal_str(st['week'])}：{a.name}と婚約した（{a.terms}）")
            save_state(st)
            print(f"婚約：{a.name}（{a.terms}）")
        elif a.action == "break":
            old = st.get("engagement")
            st["engagement"] = None
            out = Out(st)
            apply_effects(st, {"domain.名誉": -15}, out)
            append_md(LOG_MD, f"- {cal_str(st['week'])}：{old['相手'] if old else '?'}との婚約を解いた（{a.terms or a.name}）")
            save_state(st)
            print("婚約を解いた：名誉 −15。相手の家の態度 −4 を GM が反映すること")
    elif a.cmd == "rewind":
        y = cal(st["week"])[0]
        used = st["protagonist"].setdefault("刻戻り", {}).get(str(y))
        if a.action == "status":
            print(f"刻戻り（{y}年）：{'使った（' + used + '）' if used else 'まだ使える'}")
        elif a.action == "list":
            files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json")) if os.path.exists(SNAP_DIR) else []
            for f in files[-15:]:
                sn = load_json(os.path.join(SNAP_DIR, f)).get("_snap", {})
                print(f"  [{sn.get('n')}] {sn.get('when')}　{sn.get('label')} の直前")
            print(f"刻戻り（{y}年）：{'使った' if used else 'まだ使える'}")
        else:
            if used:
                raise SystemExit(f"{y}年の刻戻りは、もう使った（{used}）")
            path = os.path.join(SNAP_DIR, f"{a.n:05d}_.json")
            if not os.path.exists(path):
                raise SystemExit("その番号の記録がない（rewind list で確かめる）")
            old = load_json(path)
            old.pop("_snap", None)
            old["protagonist"].setdefault("刻戻り", {})[str(y)] = f"{cal_str(st['week'])}：{a.reason}"
            save_state(old)
            append_md(LOG_MD, f"- {cal_str(st['week'])}：（刻戻り）世界が少しだけ巻き戻った。{a.reason}")
            print(f"刻戻り：記録 [{a.n}] まで世界を戻した。{y}年の刻戻りを使った")
    elif a.cmd == "impression":
        r_ = st["npcs"].setdefault(a.name, {"信頼": 0, "好意": 0, "警戒": 0, "借り": 0, "next": None})
        old = r_.get("印象", "")
        r_["印象"] = a.text
        r_.setdefault("history", []).append(f"{cal_str(st['week'])}：印象「{old}」→「{a.text}」")
        save_state(st)
        print(f"〈{a.name}〉の印象：{a.text}（人物シートの「主人公への評価と印象」も更新すること）")
    elif a.cmd == "log":
        append_md(LOG_MD, f"- {cal_str(st['week'])}：{a.text}")
        print("記録しました")


def project_cmd(st, action, args):
    pdefs = defs("projects")
    if action == "list":
        print("■ 今始められる計画")
        for pid, p in pdefs.items():
            if pid in st["projects_done"] or any(x["id"] == pid for x in st["projects_active"]):
                continue
            ok = cond(st, p.get("requires"))
            if ok:
                print(f"  [{pid}] {p['name']}（段階{p['tier']}）費用 {p.get('cost',{})} 労働 {p.get('labor',0)}人週 最短{p.get('min_weeks',1)}週　許可：{p.get('permit','なし')}")
    elif action == "tree":
        tiers = {}
        for pid, p in pdefs.items():
            tiers.setdefault(p["tier"], []).append((pid, p))
        for t in sorted(tiers):
            print(f"■ 段階 {t}")
            for pid, p in tiers[t]:
                mark = "✔" if pid in st["projects_done"] else ("…" if any(x["id"] == pid for x in st["projects_active"]) else ("○" if cond(st, p.get("requires")) else "×"))
                print(f"  {mark} {p['name']}　前提：{p.get('requires_text','なし')}")
    elif action == "start":
        pid = args[0]
        people = int(args[1]) if len(args) > 1 else 0
        p = pdefs[pid]
        if not cond(st, p.get("requires")):
            raise SystemExit(f"前提を満たしていません：{p.get('requires_text', p.get('requires'))}")
        for k, v in p.get("cost", {}).items():
            if st["domain"].get(k, 0) < v:
                raise SystemExit(f"{k} が足りません（必要 {v}、ある {st['domain'].get(k,0)}）")
        for k, v in p.get("cost", {}).items():
            st["domain"][k] = round(st["domain"][k] - v, 2)
        st["projects_active"].append({"id": pid, "labor": 0, "weeks": 0, "people": people,
                                      "hero_days_needed": bool(p.get("hero_days"))})
        out = Out(st)
        apply_effects(st, p.get("start_effects"), out)
        save_state(st)
        print(f"計画「{p['name']}」を始めた（投入 {people} 人）。費用 {p.get('cost',{})}")
        if out.lines:
            print("\n".join(out.lines))
        append_md(LOG_MD, f"- {cal_str(st['week'])}：計画「{p['name']}」を始めた")
    elif action == "assign":
        pid, people = args[0], int(args[1])
        for x in st["projects_active"]:
            if x["id"] == pid:
                x["people"] = people
        save_state(st)
        print(f"{pid} に {people} 人を充てた")
    elif action == "cancel":
        st["projects_active"] = [x for x in st["projects_active"] if x["id"] != args[0]]
        save_state(st)
        print(f"{args[0]} を取りやめた（費用は戻らない）")


if __name__ == "__main__":
    main()
