"""戦の台帳（ハーゼル領記）

大きな戦の両陣営（王太子・辺境伯 と 摂政）の、兵・兵糧・金・士気を、週ごとに数で動かす。
hazel.py の advance から war_week(st, out) が毎週呼ばれる。

台帳は st["war"]：
  sides: { 陣営名: { troops: {兵種: 数}, 兵糧: 兵の週（1人を1週養う分＝1）, 金: 金貨,
                     士気: 0〜10, 入り: {名: 兵の週/週}, 金の入り: 金貨/週, 給金: {兵種: 金貨/人/週} } }
  mode: 対峙 | 和議 | 行軍
兵糧の残りの週 = 兵糧 ÷ 兵の数。

入りの名前と旗：入りの各項目は、旗の条件（if）を満たすときだけ入る。例 "海の道": {"週": 1000, "if": "flag_摂政_麦の別の道"}
"""
import random

MODE_K = {"対峙": 1.0, "和議": 1.0, "行軍": 1.2}


def total(side):
    return sum(side["troops"].values())


def weeks_left(side):
    t = total(side)
    return side["兵糧"] / t if t else 99


def war_week(st, out, cond, apply_effects, append_md, gm_log, cal_str):
    W = st.get("war")
    if not W or not W.get("on"):
        return
    k = MODE_K.get(W.get("mode", "対峙"), 1.0)
    y_m_w = cal_str(st["week"])
    # 刈り入れ：夏の終わりに、一度だけ麦が入る（作柄で増減）
    m, wk = st["_mw"](st["week"])
    if (m, wk) == (8, 4):
        h = st.get("world_harvest") or "平年"
        kk = {"凶作": 0.5, "平年": 1.0, "豊作": 1.3}.get(h, 1.0)
        for name, s in W["sides"].items():
            s["兵糧"] += int(s.get("刈り入れ", 0) * kk)
    for name, s in W["sides"].items():
        t = total(s)
        # 兵糧
        inc = 0
        for src, v in s.get("入り", {}).items():
            if cond(st, v.get("if")):
                inc += v["週"]
        s["兵糧"] = max(0, round(s["兵糧"] + inc - t * k))
        # 金
        pay = sum(s["troops"].get(u, 0) * p for u, p in s.get("給金", {}).items())
        s["金"] = round(s["金"] + s.get("金の入り", 0) - pay, 1)
        unpaid = s["金"] < 0
        if unpaid:
            s["金"] = 0
        # 士気
        wl = weeks_left(s)
        dm = (5.5 - s["士気"]) * 0.03
        if wl < 4:
            dm -= 0.15
        if wl < 2:
            dm -= 0.3
        if unpaid:
            dm -= 0.3
        if W.get("mode") == "和議":
            dm += 0.03
        s["士気"] = round(max(0, min(10, s["士気"] + dm)), 2)
        # 逃げる兵
        lost = {}
        if s["士気"] < 4 or wl < 1 or unpaid:
            for u, n in s["troops"].items():
                r = 0.01 if s["士気"] < 4 else 0
                if wl < 1:
                    r += 0.04
                if unpaid and u == "傭兵":
                    r += 0.06
                if s["士気"] < 2:
                    r += 0.03
                d = int(n * r + (1 if random.random() < (n * r) % 1 else 0))
                if d:
                    s["troops"][u] = n - d
                    lost[u] = d
        if lost:
            txt = "、".join(f"{u} {n}" for u, n in lost.items())
            append_md(gm_log, f"- {y_m_w}：（戦の台帳）{name}の兵が逃げた：{txt}（士気 {s['士気']}、兵糧 残り {wl:.1f} 週{'、給金が払えない' if unpaid else ''}）")
            if sum(lost.values()) >= 30:
                out.report(f"［戦］{s.get('呼び名', name)}の陣から、兵が逃げはじめているという", stop=False, log=True)
        # 旗：クロックとのつながり
        tag = s.get("旗", name)
        st["flags"][f"{tag}_兵糧不足"] = wl < 4
        st["flags"][f"{tag}_兵糧十分"] = wl >= 10 and s["士気"] >= 6
        st["flags"][f"{tag}_士気低い"] = s["士気"] < 4


def summary(st, mine_only=False):
    W = st.get("war")
    if not W:
        return "（戦の台帳はない）"
    lines = [f"■ 戦の台帳（{W.get('mode', '対峙')}）"]
    for name, s in W["sides"].items():
        if mine_only and s.get("敵"):
            # 敵の数は、見張りと商人の耳からの見こみ（±2割）
            t = total(s)
            lines.append(f"  {s.get('呼び名', name)}（見こみ）：兵 およそ {round(t, -2):.0f}　兵糧 およそ {weeks_left(s):.0f} 週分　士気 {'高い' if s['士気'] >= 6 else '低い' if s['士気'] < 4 else 'ふつう'}")
            continue
        troops = " / ".join(f"{u} {n}" for u, n in s["troops"].items())
        lines.append(f"  {s.get('呼び名', name)}：兵 {total(s)}（{troops}）　兵糧 {s['兵糧']}（残り {weeks_left(s):.1f} 週）　金 {s['金']}　士気 {s['士気']}")
        inc = " / ".join(f"{k} {v['週']}" + ("" if not v.get("if") else f"［{v['if']}］") for k, v in s.get("入り", {}).items())
        lines.append(f"      兵糧の入り（週）：{inc}　金の入り {s.get('金の入り', 0)}/週")
    return "\n".join(lines)
