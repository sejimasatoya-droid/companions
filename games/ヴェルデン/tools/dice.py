#!/usr/bin/env python3
"""さいころ（ヴェルデン）。2d6 ＋ 能力 ＋ 技能 で振る。

  python tools/dice.py 2d6+3            … 式をそのまま振る（1d6, 2d6+1, 3d6-2, d66 など）
  python tools/dice.py check 4 9        … 判定：2d6＋修正4 で目標9。会心・紙一重・大失敗も出す
  python tools/dice.py check 4 9 x3     … 同じ判定を3回
  python tools/dice.py dmg 1d6+3 2      … ダメージ：式を振って、防護2を引く（0未満は0）
  python tools/dice.py death 2 -4 1     … 生死判定：頑健2、いまの体力-4、重傷の数1
  python tools/dice.py opinion 1 20     … 意見の強さ：押しの強さ1、好感度20（NPCの意見表明）
  python tools/dice.py initiative 2     … 仕掛け手番：能動性2（10以上で仕掛ける）
  python tools/dice.py pick 6           … 1〜6 から一つ（表の行を選ぶとき）

出目は必ず記録に残す（gm/判断記録.md）。
"""
import random, re, sys


def roll_expr(expr):
    expr = expr.replace(" ", "").lower()
    if expr == "d66":
        a, b = random.randint(1, 6), random.randint(1, 6)
        return a * 10 + b, f"d66 = {a}{b}"
    total, parts = 0, []
    for sign, term in re.findall(r"([+-]?)([^+-]+)", expr):
        k = -1 if sign == "-" else 1
        m = re.fullmatch(r"(\d*)d(\d+)", term)
        if m:
            n, s = int(m.group(1) or 1), int(m.group(2))
            rs = [random.randint(1, s) for _ in range(n)]
            total += k * sum(rs)
            parts.append(f"{sign}{term}[{','.join(map(str, rs))}]")
        else:
            total += k * int(term)
            parts.append(f"{sign}{term}")
    return total, "".join(parts).lstrip("+") + f" = {total}"


def check(mod, target):
    a, b = random.randint(1, 6), random.randint(1, 6)
    t = a + b + mod
    if a == b == 6:
        r = "会心（6ゾロ：自動成功、効果が一段上がる）"
    elif a == b == 1:
        r = "大失敗（1ゾロ：自動失敗、厄介ごとが起きる）"
    elif t >= target:
        r = "成功" + ("（目標を4以上超えた：見事）" if t >= target + 4 else "")
    elif t == target - 1:
        r = "紙一重（成功するが、代償か厄介ごと）"
    else:
        r = "失敗"
    return f"2d6[{a},{b}]{mod:+d} = {t} / 目標{target} → {r}"


def death(con, hp, wounds):
    target = 8 + (abs(hp) + 1) // 2 + wounds
    a, b = random.randint(1, 6), random.randint(1, 6)
    t = a + b + con
    if a == b == 6:
        r = "持ち直す（意識が戻る。体力1）"
    elif a == b == 1:
        r = "失敗2つぶん"
    elif t >= target:
        r = "成功（持ちこたえる）"
    else:
        r = "失敗"
    return f"生死判定 2d6[{a},{b}]+頑健{con} = {t} / 目標{target}（8＋体力のマイナス{abs(hp)}の半分＋重傷{wounds}）→ {r}"


def opinion(push, like):
    a, b = random.randint(1, 6), random.randint(1, 6)
    adj = 0
    if like >= 60:
        adj = -2
    elif like >= 30:
        adj = -1
    elif like <= -60:
        adj = 2
    elif like <= -30:
        adj = 1
    t = a + b + push + adj
    if t <= 5:
        r = "従う（不満があっても今回は乗る。帳面に残す）"
    elif t <= 8:
        r = "意見だけ言う（反対・別案を口にするが、決定には従う）"
    elif t <= 11:
        r = "押し通そうとする（説得されないかぎり譲らない。条件をつける）"
    else:
        r = "単独で動く（自分の価値観に強く反するなら、一人でもやる・抜ける）"
    return f"意見 2d6[{a},{b}]+押し{push}{adj:+d}(好感度{like}) = {t} → {r}"


def initiative(act):
    a, b = random.randint(1, 6), random.randint(1, 6)
    t = a + b + act
    r = "仕掛ける（未着手の意図から一つ実行）" if t >= 10 else "様子を見る"
    return f"仕掛け 2d6[{a},{b}]+能動{act} = {t} / 10 → {r}"


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "check":
        mod, target = int(argv[1]), int(argv[2])
        n = int(argv[3][1:]) if len(argv) > 3 and argv[3].startswith("x") else 1
        for _ in range(n):
            print(check(mod, target))
    elif cmd == "dmg":
        v, s = roll_expr(argv[1])
        arm = int(argv[2]) if len(argv) > 2 else 0
        print(f"{s} − 防護{arm} → {max(0, v - arm)} 点")
    elif cmd == "death":
        print(death(int(argv[1]), int(argv[2]), int(argv[3]) if len(argv) > 3 else 0))
    elif cmd == "opinion":
        print(opinion(int(argv[1]), int(argv[2]) if len(argv) > 2 else 0))
    elif cmd == "initiative":
        for a in argv[1:] or ["0"]:
            print(initiative(int(a)))
    elif cmd == "pick":
        n = int(argv[1])
        print(f"1〜{n} → {random.randint(1, n)}")
    else:
        for e in argv:
            print(roll_expr(e)[1])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
