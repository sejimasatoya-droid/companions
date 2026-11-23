#!/usr/bin/env python3
"""灰燈の学院のさいころ。
  python3 tools/roll.py 1d100            … 1d100 を振る
  python3 tools/roll.py check 55 [難]    … 目標 55 の下方ロール。難＝簡単|普通|至難（レギュラー|ハード|イクストリーム）
  python3 tools/roll.py 1d10+5           … 足し算つき
"""
import random, re, sys

def dice(expr):
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr)
    if not m:
        raise SystemExit(f"式が読めません: {expr}")
    n, s, k = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)
    rs = [random.randint(1, s) for _ in range(n)]
    return rs, sum(rs) + k, k

def check(target, tier="簡単"):
    div = {"簡単": 1, "レギュラー": 1, "普通": 2, "ハード": 2, "至難": 5, "イクストリーム": 5}[tier]
    need = target // div
    r = random.randint(1, 100)
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
    print(f"🎲 1d100 = {r}　目標 {target}（{tier}：{need} 以下）→ {res}")

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit()
    if a[0] == "check":
        check(int(a[1]), a[2] if len(a) > 2 else "簡単")
    else:
        rs, tot, k = dice(a[0])
        print(f"🎲 {a[0]}：{rs}{('%+d' % k) if k else ''} → {tot}")
