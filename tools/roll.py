#!/usr/bin/env python3
"""語り手用のダイス。Claude が展開を自分で選ばないために使う。

使い方:
  python3 tools/roll.py check 54 1 13          # 判定: 能力値54・技能1・目標値13
  python3 tools/roll.py check 54 1 13 -2       # 状況修正つき（±3まで）
  python3 tools/roll.py grow 30                # 住人の能力値成長判定
  python3 tools/roll.py grow 30 transferee     # 転移者・勇者の魂の能力値成長判定
  python3 tools/roll.py 1d6+1                  # 普通に振る（ダメージなど）
  python3 tools/roll.py pick 晴れ 雨 霧         # 候補から1つ選ぶ
  python3 tools/roll.py event                  # 町の偶然の出来事の良し悪し
"""
import random
import re
import sys

EVENT_TABLE = {
    1: "悪いこと（誰かが困る・何かが壊れる・揉め事）",
    2: "悪いこと（小さな不運）",
    3: "どちらでもない（ただの変化・知らせ）",
    4: "どちらでもない（新しい人や物が来る）",
    5: "良いこと（小さな幸運）",
    6: "良いこと（はっきりした幸運）",
}


def dice(expr: str) -> tuple[int, list[int], int]:
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr)
    if not m:
        sys.exit(f"書式が違います: {expr}（例: 2d6, 1d6+1）")
    n = int(m.group(1) or 1)
    sides = int(m.group(2))
    mod = int(m.group(3) or 0)
    rolls = [random.randint(1, sides) for _ in range(n)]
    return sum(rolls) + mod, rolls, mod


def check(ability: int, skill: int, target: int, situational: int = 0) -> str:
    situational = max(-3, min(3, situational))
    mod = ability // 10 + skill + situational
    rolls = [random.randint(1, 6) for _ in range(3)]
    raw = sum(rolls)
    total = raw + mod
    if raw == 3:
        result = "自動失敗"
    elif raw == 18:
        result = "自動成功"
    elif total >= target + 5:
        result = "大成功"
    elif total >= target:
        result = "成功"
    else:
        result = "失敗"
    sit = f"{situational:+d}" if situational else ""
    return (f"〔能力{ability}+技能{skill}{sit} → {mod:+d}｜目標{target}〕"
            f"3d6={rolls}={raw} → {total} {result}")


def grow(value: int, transferee: bool) -> str:
    r = random.randint(1, 100)
    threshold = value // 2 if transferee else value
    if r > threshold:
        gain = random.randint(1, 3) if transferee else 1
        kind = "成長"
    else:
        gain = 0
        kind = "伸び悩み"
    who = "転移者・勇者の魂" if transferee else "住人"
    cap = 200 if transferee else 100
    after = min(value + gain, cap)
    gain = after - value
    note = ""
    if after // 10 > value // 10:
        note = f"  ★修正値が +{value // 10} → +{after // 10} に上がった"
    return (f"〔成長判定・{who}｜1d100={r} vs {threshold}〕"
            f"{kind} +{gain} → {value} → {after}{note}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd = args[0]
    if cmd == "check":
        if len(args) < 4:
            sys.exit("使い方: check <能力値> <技能> <目標値> [状況修正]")
        sit = int(args[4]) if len(args) > 4 else 0
        print(check(int(args[1]), int(args[2]), int(args[3]), sit))
    elif cmd == "grow":
        if len(args) < 2:
            sys.exit("使い方: grow <現在値> [transferee]")
        print(grow(int(args[1]), len(args) > 2 and args[2] == "transferee"))
    elif cmd == "pick":
        if len(args) < 2:
            sys.exit("候補を1つ以上指定してください")
        print(random.choice(args[1:]))
    elif cmd == "event":
        r = random.randint(1, 6)
        print(f"1d6={r}: {EVENT_TABLE[r]}")
    else:
        total, rolls, mod = dice(cmd)
        print(f"〔{cmd}〕{rolls}{mod:+d} = {total}" if mod else f"〔{cmd}〕{rolls} = {total}")


if __name__ == "__main__":
    main()
