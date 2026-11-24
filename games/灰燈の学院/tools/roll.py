#!/usr/bin/env python3
"""灰燈の学院のさいころ。
  python3 tools/roll.py 1d100            … 1d100 を振る
  python3 tools/roll.py check 55 [難]    … 目標 55 の下方ロール。難＝簡単|普通|至難（レギュラー|ハード|イクストリーム）
  python3 tools/roll.py 1d10+5           … 足し算つき
  python3 tools/roll.py vs 84 89         … 対抗（左が仕掛ける側、右が守る側）
  ボーナス・ペナルティダイス：末尾に b2（ボーナス 2 つ）や p1（ペナルティ 1 つ）。対抗では a: と d: で側を分ける
    python3 tools/roll.py check 82 簡単 b1
    python3 tools/roll.py vs 84 89 a:b1 d:p2
"""
import random, re, sys

def dice(expr):
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr)
    if not m:
        raise SystemExit(f"式が読めません: {expr}")
    n, s, k = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)
    rs = [random.randint(1, s) for _ in range(n)]
    return rs, sum(rs) + k, k

RANK = {"大失敗": 0, "失敗": 1, "紙一重": 2, "成功": 3, "会心": 4}

def d100(bp=0):
    """bp>0：ボーナス（十の位を余分に振って低いほう）、bp<0：ペナルティ（高いほう）"""
    one = random.randint(0, 9)
    tens = [random.randint(0, 9) for _ in range(1 + abs(bp))]
    vals = [(10 * t + one) or 100 for t in tens]
    r = min(vals) if bp > 0 else max(vals) if bp < 0 else vals[0]
    note = "" if bp == 0 else f"（{'ボーナス' if bp > 0 else 'ペナルティ'} {abs(bp)}：候補 {vals}）"
    return r, note

def parse_bp(xs):
    bp = 0
    for x in xs:
        x = x.split(":")[-1]
        if x[:1] == "b": bp += int(x[1:] or 1)
        if x[:1] == "p": bp -= int(x[1:] or 1)
    return bp

def level(target, bp=0):
    r, note = d100(bp)
    if r >= 96: return r, "大失敗", note
    if r <= max(1, target // 5): return r, "会心", note
    if r <= target: return r, "成功", note
    if r <= target + 10: return r, "紙一重", note
    return r, "失敗", note

def vs(a, b, abp=0, dbp=0):
    ra, la, na = level(a, abp); rb, lb, nb = level(b, dbp)
    if RANK[la] != RANK[lb]:
        win = "仕掛ける側" if RANK[la] > RANK[lb] else "守る側"
    elif a != b:
        win = "仕掛ける側" if a > b else "守る側"
    else:
        win = "守る側"
    print(f"🎲 仕掛ける側 1d100 = {ra}{na}（値 {a}）→ {la} ／ 守る側 1d100 = {rb}{nb}（値 {b}）→ {lb}　⇒ {win}の勝ち")

def check(target, tier="簡単", bp=0):
    div = {"簡単": 1, "レギュラー": 1, "普通": 2, "ハード": 2, "至難": 5, "イクストリーム": 5}[tier]
    need = target // div
    r, note = d100(bp)
    if r >= 96:
        res = "大失敗"
    elif r <= max(1, target // 5) and div == 1:
        res = "会心"
    elif r <= need:
        res = "成功"
    elif div == 1 and r <= target + 10:
        res = "紙一重（成功。ただし代償か厄介ごと）"
    else:
        res = "失敗"
    print(f"🎲 1d100 = {r}{note}　目標 {target}（{tier}：{need} 以下）→ {res}")

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit()
    if a[0] == "vs":
        rest = a[3:]
        vs(int(a[1]), int(a[2]), parse_bp([x for x in rest if x.startswith("a:")]), parse_bp([x for x in rest if x.startswith("d:")]))
    elif a[0] == "check":
        tier = a[2] if len(a) > 2 and not a[2][:1] in "bp" else "簡単"
        check(int(a[1]), tier, parse_bp([x for x in a[2:] if x[:1] in "bp"]))
    else:
        rs, tot, k = dice(a[0])
        print(f"🎲 {a[0]}：{rs}{('%+d' % k) if k else ''} → {tot}")
