# 巡り湯 第一話 釣り合いの確かめ
import random, sys
LOC = ["湯屋","停車場","写真館","製糸場"]
ADJ = {"湯屋":{"停車場","写真館"},"停車場":{"湯屋","製糸場"},"写真館":{"湯屋","製糸場"},"製糸場":{"停車場","写真館"}}
CH = ["源治","篠","有馬","たえ","清彦","三条"]
START = {"源治":"湯屋","篠":"湯屋","有馬":"停車場","たえ":"製糸場","清彦":"製糸場","三条":"写真館"}
MOOD0 = {"源治":0,"篠":0,"有馬":0,"たえ":0,"清彦":-1,"三条":0}
FORBID = {"たえ":{"停車場"},"清彦":{"湯屋"}}
ROLE = {"たえ":"要","三条":"糸引き","清彦":"刃","篠":"守り手","有馬":"迷い子","源治":"ただの人"}
INC = {2:("失踪","源治",-1), 3:("火事","有馬",-2), 4:("殺め","清彦",-1)}
DAYS = 4

def can(c, to): return to not in FORBID.get(c,set())

def play_loop(r, mm, pp, know):
    pos = dict(START); mood = dict(MOOD0); gone = set(); pawns = ["湯屋","湯屋"]
    once_m = {"煽る":1,"呼び出す":1}; once_p = {"励ます":1,"見守る":2}
    for d in range(1, DAYS+1):
        alive = [c for c in CH if c not in gone]
        pawns = pp.pawns(r, d, pos, mood, pawns, alive, know)
        mcards = mm(r, d, pos, mood, alive, once_m)
        pcards = pp.cards(r, d, pos, mood, alive, once_p, know)
        # 解決
        stop = {c for c,k in pcards.items() if k == "足止め"}
        mv = {}
        for side in (mcards, pcards):
            for c,k in side.items():
                if k in LOC: mv.setdefault(c, []).append(k)
        for c, ks in mv.items():
            if c in stop or len(ks) > 1: continue
            to = ks[0]
            if to in ADJ[pos[c]] and can(c, to): pos[c] = to
        for c,k in mcards.items():
            if isinstance(k, tuple) and k[0] == "呼び出す" and c not in stop:
                to = pos[k[1]]
                if can(c, to): pos[c] = to
        guard = {c for c,k in pcards.items() if k == "見守る"}
        for c,k in list(mcards.items()) + list(pcards.items()):
            delta = {"荒らす":-1,"煽る":-2,"和ませる":1,"励ます":2}.get(k if isinstance(k,str) else "", 0)
            if delta < 0 and c in guard: delta = 0
            if delta > 0 and ROLE[c] == "迷い子" and pos[c] not in pawns: delta = 0
            mood[c] = max(-3, min(3, mood[c]+delta))
        # 糸引き：同じ場所の一人を−1（要を優先、次に犯人）
        if "三条" not in gone:
            near = [c for c in alive if pos[c] == pos["三条"] and c != "三条"]
            near = [c for c in near if c not in guard]
            if near:
                pri = [x for x in ("清彦","有馬","源治") if x in near]
                t = pri[0] if pri else r.choice(near)
                if ROLE[t] != "迷い子" or True: mood[t] = max(-3, mood[t]-1)
        # 刃
        if "清彦" not in gone and mood["清彦"] == -3:
            here = [c for c in alive if pos[c] == pos["清彦"] and c != "清彦"]
            if pos["清彦"] in pawns: return True, "刃が逗留客を"
            if here:
                v = "たえ" if "たえ" in here else r.choice(here)
                if not (v == "たえ" and pos["篠"] == pos["たえ"] and "篠" not in gone):
                    gone.add(v)
                    if v == "たえ": return True, "刃"
        # 事件
        if d in INC:
            kind, cul, th = INC[d]
            if cul in gone or mood[cul] > th: continue
            if kind == "火事": return True, "火事"
            here = [c for c in CH if c not in gone and pos[c] == pos[cul] and c != cul]
            if len(here) == 1 and pos[cul] not in pawns:
                v = here[0]
                if v == "たえ" and pos["篠"] == pos["たえ"] and "篠" not in gone: continue
                gone.add(v)
                if v == "たえ": return True, kind
    return False, ""

# ---- 黒幕（方針表の形：重みつき乱数） ----
def mastermind(r, d, pos, mood, alive, once):
    cards = {}
    nxt = INC.get(d) or INC.get(d+1)
    cand = []
    for dd in (d, d+1, d+2):
        if dd in INC and INC[dd][1] in alive: cand.append(INC[dd])
    used = set()
    # 犯人を下げる
    for kind, cul, th in cand:
        if len(cards) >= 3: break
        if mood[cul] > th and cul not in cards:
            if once["煽る"] and mood[cul] - th >= 2 and r.random() < .6:
                cards[cul] = "煽る"; once["煽る"] = 0
            elif "荒らす1" not in used: cards[cul] = "荒らす"; used.add("荒らす1")
            elif "荒らす2" not in used: cards[cul] = "荒らす"; used.add("荒らす2")
    # 二人きりを作る：その日の事件の犯人の所へ要を寄せる
    if d in INC and INC[d][0] != "火事" and "たえ" in alive and len(cards) < 3:
        cul = INC[d][1]
        if pos["たえ"] != pos[cul] and "たえ" not in cards:
            if pos[cul] in ADJ[pos["たえ"]] and can("たえ", pos[cul]) and r.random() < .7:
                cards["たえ"] = pos[cul]
            elif once["呼び出す"] and can("たえ", pos[cul]):
                cards["たえ"] = ("呼び出す", cul); once["呼び出す"] = 0
        # 邪魔な第三者を追い出す
        others = [c for c in alive if pos[c] == pos[cul] and c not in (cul, "たえ")]
        for o in others:
            if len(cards) >= 3: break
            if o not in cards:
                dests = [x for x in ADJ[pos[o]] if can(o, x)]
                if dests: cards[o] = r.choice(dests)
    # 残りは乱数で荒らすか動かす
    while len(cards) < 3:
        c = r.choice([x for x in alive if x not in cards] or alive)
        if c in cards: break
        if r.random() < .5 and "荒らす2" not in used:
            cards[c] = "荒らす"; used.add("荒らす1" if "荒らす1" not in used else "荒らす2")
        else:
            dests = [x for x in ADJ[pos[c]] if can(c, x)]
            cards[c] = r.choice(dests) if dests else "荒らす"
    return cards

class RandomP:
    def pawns(self, r, d, pos, mood, pawns, alive, know):
        return [r.choice(list(ADJ[p]) + [p]) for p in pawns]
    def cards(self, r, d, pos, mood, alive, once, know):
        cs = {}
        opts = ["和ませる","和ませる","足止め"] + LOC
        for c in r.sample(alive, min(3, len(alive))):
            pool = opts + [k for k in ("励ます","見守る") if once[k] > 0]
            k = r.choice(pool)
            if k in once: once[k] -= 1
            cs[c] = k
        return cs

class InformedP:
    """know: 'all' 役と犯人を知る / 'timeline' 事件の日だけ知る（犯人は知らない）"""
    def pawns(self, r, d, pos, mood, pawns, alive, know):
        # 一つは要に付き添い、もう一つは事件の犯人の所へ
        tgt = [pos["たえ"]]
        if know == "all" and d in INC and INC[d][1] in alive: tgt.append(pos[INC[d][1]])
        else: tgt.append(pos[r.choice(alive)])
        out = []
        for p, t in zip(pawns, tgt):
            out.append(t if (t == p or t in ADJ[p]) else r.choice(list(ADJ[p] & ADJ[t]) or [p]))
        return out
    def cards(self, r, d, pos, mood, alive, once, know):
        cs = {}
        if know == "all":
            culs = [INC[dd][1] for dd in (d, d+1) if dd in INC and INC[dd][1] in alive]
            for c in culs:
                if len(cs) < 3 and c not in cs:
                    if c == "有馬":
                        if once["見守る"] > 0 and d >= 2: cs[c] = "見守る"; once["見守る"] -= 1
                        continue
                    if once["励ます"] and mood[c] <= -1: cs[c] = "励ます"; once["励ます"] = 0
                    else: cs[c] = "和ませる"
            if "たえ" in alive and len(cs) < 3: cs["たえ"] = "足止め"

            while len(cs) < 3:
                c = r.choice([x for x in alive if x not in cs]); cs[c] = "和ませる"
        else:
            if "たえ" in alive: cs["たえ"] = "足止め"
            low = sorted([c for c in alive if c not in cs], key=lambda c: mood[c])
            if once["見守る"] > 0 and d >= 2: cs[low[0]] = "見守る"; once["見守る"] -= 1
            else: cs[low[0]] = "和ませる"
            cs[low[1]] = "和ませる"
        return cs

N = 20000
r = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
for name, pp, know in [("乱数の主人公", RandomP(), None), ("事件の日だけ知る", InformedP(), "timeline"), ("役と犯人を知り尽くす", InformedP(), "all")]:
    lose = 0; why = {}
    for _ in range(N):
        l, w = play_loop(r, mastermind, pp, know)
        lose += l; why[w] = why.get(w, 0) + l
    print(f"{name}: 一周を越える {1-lose/N:.3f}", {k: round(v/N,3) for k,v in why.items() if v})
