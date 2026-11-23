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
    # 全軍の計画：王太子の側の金で、ハーゼルの技を軍全体へ広げる。一つずつ順に進む
    #   W["全軍の計画"] = [{名, 旗, 費用, 週, 残り, if?, 文}]
    q = W.get("全軍の計画") or []
    if q and "王太子" in W["sides"]:
        pr = W["sides"]["王太子"]
        cur = q[0]
        if not cur.get("始めた"):
            if (not cur.get("if") or cond(st, cur["if"])) and pr["金"] >= cur["費用"]:
                pr["金"] = round(pr["金"] - cur["費用"], 1)
                cur["始めた"] = True
                cur["残り"] = cur["週"]
                append_md(gm_log, f"- {y_m_w}：（戦の台帳）全軍の計画「{cur['名']}」を始めた（王太子の金 −{cur['費用']}）")
        else:
            cur["残り"] -= 1
            if cur["残り"] <= 0:
                st["flags"][cur["旗"]] = True
                q.pop(0)
                out.report(f"［戦］全軍の計画「{cur['名']}」ができた。{cur.get('文', '')}", stop=False, log=True)
        W["全軍の計画"] = q
    # 兵糧狩り：毎月の第3週、王太子の側の小隊が、摂政の麦の列を叩く
    if st["flags"].get("兵糧狩り") and W.get("mode") != "和議" and (wk == 3 or (wk == 1 and st["flags"].get("兵糧狩り_月二度"))) and "摂政" in W["sides"] and "王太子" in W["sides"]:
        r = random.randint(1, 6) + random.randint(1, 6)
        lead = (1 if st["flags"].get("長弓隊") else 0) + (1 if st["flags"].get("商会の耳") else 0) + (1 if st["flags"].get("全軍_遠眼鏡") else 0) + (1 if st["flags"].get("夜の襲い") else 0) + (1 if st["flags"].get("全軍_襲撃隊") else 0)
        guard = W.get("摂政の護り", 0)
        tot = r + lead - guard
        reg, pr = W["sides"]["摂政"], W["sides"]["王太子"]
        if tot >= 10:
            reg["兵糧"] = max(0, reg["兵糧"] - 2500); W["摂政の護り"] = min(4, guard + 1)
            txt = "白樺の谷道で、また摂政の麦の列を焼いた（大きく）"
            loss = 3
        elif tot >= 7:
            reg["兵糧"] = max(0, reg["兵糧"] - 1200); W["摂政の護り"] = min(4, guard + 1)
            txt = "白樺の谷道で、摂政の麦の列の一部を焼いた"
            loss = 6
        else:
            txt = "摂政の麦の列を狩りに出たが、守りが厚く、退いた"
            loss = 12
        div = (2 if st["flags"].get("野戦の手当て") else 1) * (2 if st["flags"].get("全軍_手当て") else 1)
        pr["troops"]["兵"] = max(0, pr["troops"].get("兵", 0) - (loss // div))
        out.report(f"［戦］{txt}（🎲{r}+{lead}−守り{guard}＝{tot}）", stop=False, log=True)
        append_md(gm_log, f"- {y_m_w}：（戦の台帳）兵糧狩り {tot}：摂政の兵糧 {reg['兵糧']}、守り {W.get('摂政の護り', 0)}、味方の損害 {loss}")
    # ザルム狩り：毎月の第1週、ザルム領から摂政の陣へ出る麦の荷と、ザルムの蔵を叩く
    #   旗 ザルム狩り_村も があれば村の蔵まで焼く（効きは大きいが、名誉・民の恨み）
    if st["flags"].get("ザルム狩り") and W.get("mode") != "和議" and wk == 1 and "摂政" in W["sides"] and "王太子" in W["sides"]:
        r = random.randint(1, 6) + random.randint(1, 6)
        lead = (1 if st["flags"].get("襲撃隊") else 0) + (1 if st["flags"].get("全軍_遠眼鏡") else 0) \
            + (1 if st["flags"].get("領の地図") or st["flags"].get("地図づくり") else 0) + (1 if st["flags"].get("夜の襲い") else 0) \
            + (1 if st["flags"].get("全軍_地図") else 0) + (1 if st["flags"].get("全軍_襲撃隊") else 0)
        guard = W.get("ザルムの守り", 0)
        tot = r + lead - guard
        reg, pr = W["sides"]["摂政"], W["sides"]["王太子"]
        inc = reg["入り"].get("ザルムの蔵")
        village = st["flags"].get("ザルム狩り_村も")
        if tot >= 10:
            cut, burn, loss, txt = 250, 1500, 3, "ザルム領の蔵を焼き、摂政の陣へ向かう荷を奪った（大きく）"
        elif tot >= 7:
            cut, burn, loss, txt = 150, 700, 6, "ザルム領で、摂政の陣へ向かう荷の一部を焼いた"
        else:
            cut, burn, loss, txt = 0, 0, 12, "ザルム領の蔵を狙ったが、見張りに気づかれ、退いた"
        if village and cut:
            cut, burn = int(cut * 1.5), int(burn * 1.5)
            apply_effects(st, {"domain.名誉": -2, "clocks.イゾルデの恨み": 1})
            txt += "。村の蔵にも火をかけた"
        if inc and cut:
            inc["週"] = max(300, inc["週"] - cut)
        reg["兵糧"] = max(0, reg["兵糧"] - burn)
        if cut:
            W["ザルムの守り"] = min(4, guard + 1)
        div = (2 if st["flags"].get("野戦の手当て") else 1) * (2 if st["flags"].get("全軍_手当て") else 1)
        pr["troops"]["兵"] = max(0, pr["troops"].get("兵", 0) - (loss // div))
        out.report(f"［戦］{txt}（🎲{r}+{lead}−守り{guard}＝{tot}）", stop=False, log=True)
        append_md(gm_log, f"- {y_m_w}：（戦の台帳）ザルム狩り {tot}：ザルムの蔵の入り {inc['週'] if inc else '-'}/週、摂政の兵糧 {reg['兵糧']}、ザルムの守り {W.get('ザルムの守り', 0)}、味方の損害 {loss}")
    # 挑発の策：焼きながら誘い、摂政の軍が出てくるのを待つ。毎月の第 4 週に、摂政が出てくるかを振る
    if st["flags"].get("挑発の策") and not st["flags"].get("摂政の出撃") and W.get("mode") == "対峙" and wk == 4 and "摂政" in W["sides"]:
        reg = W["sides"]["摂政"]
        r = random.randint(1, 6) + random.randint(1, 6)
        mod = (2 if weeks_left(reg) < 6 else 0) + (1 if W.get("ザルムの守り", 0) >= 2 else 0) + (1 if reg["士気"] < 4 else 0) + W.get("挑発の積み", 0)
        W["挑発の積み"] = W.get("挑発の積み", 0) + 1
        append_md(gm_log, f"- {y_m_w}：（戦の台帳）挑発：摂政が出てくるか 🎲{r}+{mod}＝{r+mod}（10 以上で出る）")
        if r + mod >= 10:
            st["flags"]["摂政の出撃"] = True
            out.report("［戦］摂政の軍が、焼かれ続ける麦の道を守るため、ザルム川を越えて北へ出てきた", stop=True, log=True)
    for name, s in W["sides"].items():
        t = total(s)
        # 金のある側は、兵糧が細れば、高値で麦を買い足す（摂政の打ち返し）。8 週に一度まで
        if weeks_left(s) < 3 and s["金"] >= 600 and st["week"] - s.get("_買い足し", -99) >= 8:
            s["金"] -= 400
            s["兵糧"] += 4000
            s["_買い足し"] = st["week"]
            append_md(gm_log, f"- {y_m_w}：（戦の台帳）{name}が、兵糧が細ったので、高値で麦を買い足した（金 −400、兵糧 +4000）")
            if s.get("敵"):
                out.report(f"［戦］{s.get('呼び名', name)}が、南から麦を高値で買い足したという", stop=False, log=True)
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
        if s.get("煮沸") or (name == "王太子" and st["flags"].get("全軍_煮沸")):
            dm += 0.03  # 陣の煮沸と手洗い：腹下しが減る
        if s.get("敵") and st["flags"].get("投げ文") and W.get("mode") != "和議":
            dm -= 0.03  # 敵陣への投げ文
        if m in (12, 1, 2) and not (name == "王太子" and st["flags"].get("全軍_冬着")):
            dm -= 0.04  # 冬の寒さ（冬の外套がなければ）
        if name == "王太子" and st["flags"].get("全軍_号令"):
            dm += 0.02  # 全軍の号令：隊列に自信がつく
        s["士気"] = round(max(0, min(10, s["士気"] + dm)), 2)
        # 逃げる兵
        lost = {}
        if s["士気"] < 4 or wl < 1 or unpaid:
            for u, n in s["troops"].items():
                r = 0.01 if s["士気"] < 4 else 0
                if name == "王太子" and st["flags"].get("全軍_煮沸"):
                    r *= 0.5
                if wl < 1:
                    r += 0.04
                if unpaid and u == "傭兵":
                    r += 0.06
                if s["士気"] < 2:
                    r += 0.03
                if s.get("敵") and st["flags"].get("降る者の門"):
                    r *= 1.5
                d = int(n * r + (1 if random.random() < (n * r) % 1 else 0))
                if d:
                    s["troops"][u] = n - d
                    lost[u] = d
        if lost and s.get("敵") and st["flags"].get("降る者の門") and "王太子" in W["sides"]:
            came = int(sum(lost.values()) * 0.3)
            if came:
                W["sides"]["王太子"]["troops"]["兵"] = W["sides"]["王太子"]["troops"].get("兵", 0) + came
                append_md(gm_log, f"- {y_m_w}：（戦の台帳）降る者の門：摂政の陣から逃げた兵のうち {came} が北へ降った")
        if lost:
            txt = "、".join(f"{u} {n}" for u, n in lost.items())
            append_md(gm_log, f"- {y_m_w}：（戦の台帳）{name}の兵が逃げた：{txt}（士気 {s['士気']}、兵糧 残り {wl:.1f} 週{'、給金が払えない' if unpaid else ''}）")
            if sum(lost.values()) >= 30 and st["week"] - s.get("_逃げの知らせ", -99) >= 8:
                s["_逃げの知らせ"] = st["week"]
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
    q = W.get("全軍の計画") or []
    if q:
        lines.append("  全軍の計画（順に）：" + " → ".join(f"{c['名']}{'（残り ' + str(c['残り']) + ' 週）' if c.get('始めた') else ''}" for c in q))
    return "\n".join(lines)
