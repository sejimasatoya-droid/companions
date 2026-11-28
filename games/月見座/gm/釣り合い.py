# 月見座の釣り合いを乱数で確かめる
import random, collections, sys

MASKS = ["翁", "小面", "般若", "天狗", "狐", "素面", "素面"]
ODAI = ["平常", "平常", "公開札", "二人札", "逆さ札", "黙り札"]
MAX_ACT = 5
KOOMOTE_HALF = False  # True にすると「半分に数える」案

def tally(alive, votes, mask_of, extra):
    cnt = {p: 0 for p in alive}
    for v, t in votes.items():
        if t is None or t == v or t not in cnt:
            continue
        w = 2 if "翁" in mask_of[v] else 1
        cnt[t] += w
    for v, t2 in extra.items():  # 天狗の二枚目
        if t2 in cnt and t2 != v:
            cnt[t2] += 2 if "翁" in mask_of[v] else 1
    for p in alive:
        if "小面" in mask_of[p]:
            cnt[p] = cnt[p] // 2 if KOOMOTE_HALF else max(0, cnt[p] - 1)
    return cnt

def play(rng, focal_know=None, params=None):
    P = params if params is not None else {}
    herd = P.get("herd", 0.55)
    players = list(range(7))
    deal = MASKS[:]; rng.shuffle(deal)
    P['_deal'] = deal
    mask_of = {p: {deal[p]} for p in players}
    tengu_used = {p: False for p in players}
    odai = ODAI[:]; rng.shuffle(odai)
    alive = players[:]
    known = set()  # 退場で明かされた面の持ち主（形見の行き先は伏せ）
    focal = 0
    for act in range(MAX_ACT):
        if len(alive) <= 1:
            P['_why'] = 'one' if alive else 'zero'; return alive, act
        od = odai[act] if len(alive) > 2 else "平常"
        reverse = od == "逆さ札"
        votes, extra = {}, {}
        if len(alive) == 2:
            a, b = alive
            for p, o in ((a, b), (b, a)):
                strong = mask_of[p] & {"翁", "小面"}
                if strong and not (mask_of[o] & {"翁", "小面"}) and rng.random() < 0.85:
                    votes[p] = o
                elif rng.random() < P.get("coop", 0.5):
                    votes[p] = p
                else:
                    votes[p] = o
            cnt = tally(alive, votes, mask_of, extra)
            m = max(cnt.values())
            if m == 0:
                P['_why'] = 'pd_coop'; return alive, act + 1
            out = [p for p in alive if cnt[p] == m]
        else:
            # 群れの的：見えている強い面の持ち主を狙いやすい
            weights = []
            for p in alive:
                w = 1.0
                if p == focal and focal_know == "all":
                    w = 0.6
                weights.append(w)
            target = rng.choices(alive, weights)[0]
            for p in alive:
                if reverse:
                    # 逆さ札：誰かに書いてもらいたい。書く先は友だち（ばらばら）
                    votes[p] = rng.choice([q for q in alive if q != p])
                    continue
                r = rng.random()
                if r < 0.08:
                    votes[p] = p
                elif p != target and r < 0.08 + herd:
                    votes[p] = target
                else:
                    votes[p] = rng.choice([q for q in alive if q != p])
                # 中心の者が知っていると
                if p == focal and focal_know:
                    cands = [q for q in alive if q != p]
                    if focal_know == "all":
                        info = {q: mask_of[q] for q in cands}
                    else:
                        info = {q: mask_of[q] for q in cands if q == focal_know}
                    bad = [q for q in cands if "般若" in info.get(q, set())]
                    strong = [q for q in cands if info.get(q, set()) & {"翁", "小面"}]
                    if votes[p] in bad:
                        votes[p] = rng.choice([q for q in cands if q not in bad] or cands)
                    if strong and rng.random() < 0.6:
                        # 強い面を的にするよう皆に持ちかける
                        s = rng.choice(strong)
                        votes[p] = s
                        for q in alive:
                            if q != s and q != p and rng.random() < 0.35:
                                votes[q] = s
                if "天狗" in mask_of[p] and not tengu_used[p] and rng.random() < 0.4:
                    tengu_used[p] = True
                    extra[p] = rng.choice([q for q in alive if q not in (p, votes[p])] or [None])
            cnt = tally(alive, votes, mask_of, extra)
            if reverse:
                m = min(cnt.values())
                out = [p for p in alive if cnt[p] == m]
            else:
                m = max(cnt.values())
                out = [] if m == 0 else [p for p in alive if cnt[p] == m]
                if od == "二人札" and out and len(out) == 1:
                    rest = [cnt[p] for p in alive if p not in out]
                    m2 = max(rest) if rest else 0
                    if m2 > 0:
                        out += [p for p in alive if p not in out and cnt[p] == m2]
        # 般若の道連れ
        drag = []
        for p in out:
            if "般若" in mask_of[p]:
                cands = [v for v, t in votes.items() if t == p and v != p and v not in out]
                if cands:
                    drag.append(rng.choice(cands))
        out = list(dict.fromkeys(out + drag))
        survivors = [p for p in alive if p not in out]
        # 形見：退場者が残りの一人に面を渡す（.7）
        for p in out:
            if survivors and rng.random() < 0.7:
                r = rng.choice(survivors)
                mask_of[r] |= mask_of[p] - {"素面"}
        alive = survivors
        P.setdefault('_exits', []).append(len(out))
    if len(alive) >= 3:
        P['_why'] = 'limit'; return [], MAX_ACT
    P['_why'] = 'end%d' % len(alive); return alive, MAX_ACT


def stats(n=40000, seed=7, **kw):
    rng = random.Random(seed)
    surv = collections.Counter(); acts = collections.Counter()
    win = collections.Counter(); tot = collections.Counter(); foc = 0
    global why, ex
    why = collections.Counter(); ex = collections.Counter()
    for _ in range(n):
        P = dict(kw.get("params", {}))
        res, a = play(rng, focal_know=kw.get("focal_know"), params=P)
        surv[len(res)] += 1; acts[a] += 1
        for p, m in enumerate(P["_deal"]):
            tot[m] += 1; win[m] += p in res
        foc += 0 in res
        why[P['_why']] += 1
        for e in P.get('_exits', []): ex[e] += 1
    return surv, acts, {m: round(win[m]/tot[m], 3) for m in tot}, foc/n

if __name__ == "__main__":
    n = 40000
    for herd in (0.45, 0.55, 0.65):
        surv, acts, mr, f = stats(n, params={"herd": herd})
        print("herd", herd, "生還人数", {k: round(v/n,3) for k,v in sorted(surv.items())})
        print("   幕", {k: round(v/n,3) for k,v in sorted(acts.items())})
        print("   面", mr)
        print("   終わり方", {k: round(v/n,3) for k,v in why.items()}, "一幕の退場数", dict(sorted(ex.items())))
