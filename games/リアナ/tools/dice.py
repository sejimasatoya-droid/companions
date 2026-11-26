#!/usr/bin/env python3
"""さいころ（リアナ）。2d6 ＋ 能力 ＋ 技能 で振る。

  python tools/dice.py 2d6+3              … 式をそのまま振る（1d6, 3d6-2, d66 など）
  python tools/dice.py check 3 9          … 判定：2d6＋修正3 で目標9。会心・紙一重・大失敗も出す
  python tools/dice.py vs 3 2             … 対抗：こちら＋3、あちら＋2（同じなら守る側＝あちらの勝ち）
  python tools/dice.py gun 6 2 1          … 砲撃：砲6門、砲術＋指揮など修正2、相手の小ささ1（命中の目標が上がる）
  python tools/dice.py board 30 2 45 1    … 切り込み一合：味方30人・白兵2、敵45人・白兵1
  python tools/dice.py flee 6 2 5 1       … 離脱：こちら速さ6・航海2、あちら速さ5・航海1
  python tools/dice.py fate 1 2           … 船長の生死：体1、危うさ2（切り込みの負け・沈没・処刑など）
  python tools/dice.py initiative 2       … 仕掛け手番：能動性2（10以上で仕掛ける。ふだんは umi.py が振る）
  python tools/dice.py opinion 1 20       … 意見の強さ：押しの強さ1、船長への信頼20（−50〜50）
  python tools/dice.py policy 6           … 方針表の行を選ぶ（1〜6）。gm/方針表.md を見る
  python tools/dice.py pick 6             … 1〜6 から一つ

出目は gm/出目.log に自動で残る。理由は gm/判断記録.md に書く。
"""
import datetime, pathlib, random, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = ROOT / "gm" / "出目.log"


def d(n=2, s=6):
    return [random.randint(1, s) for _ in range(n)]


def roll_expr(expr):
    expr = expr.replace(" ", "").lower()
    if expr == "d66":
        a, b = d(2)
        return f"d66 = {a}{b}"
    total, parts = 0, []
    for sign, term in re.findall(r"([+-]?)([^+-]+)", expr):
        k = -1 if sign == "-" else 1
        m = re.fullmatch(r"(\d*)d(\d+)", term)
        if m:
            rs = d(int(m.group(1) or 1), int(m.group(2)))
            total += k * sum(rs)
            parts.append(f"{sign}{term}[{','.join(map(str, rs))}]")
        else:
            total += k * int(term)
            parts.append(f"{sign}{term}")
    return "".join(parts).lstrip("+") + f" = {total}"


def check(mod, target):
    a, b = d()
    t = a + b + mod
    if a == b == 6:
        r = "会心（自動成功、効果が一段上がる）"
    elif a == b == 1:
        r = "大失敗（自動失敗、厄介ごとが起きる）"
    elif t >= target:
        r = "成功" + ("（4以上超えた：見事）" if t >= target + 4 else "")
    elif t == target - 1:
        r = "紙一重（成功するが、代償か厄介ごと）"
    else:
        r = "失敗"
    return f"2d6[{a},{b}]{mod:+d} = {t} / 目標{target} → {r}"


def vs(m1, m2):
    a, b = d(), d()
    t1, t2 = sum(a) + m1, sum(b) + m2
    w = "こちらの勝ち" if t1 > t2 else "あちらの勝ち（同じなら守る側）"
    return f"こちら 2d6{a}{m1:+d} = {t1}　あちら 2d6{b}{m2:+d} = {t2} → {w}（差 {abs(t1 - t2)}）"


def gun(guns, mod, small):
    a, b = d()
    t = a + b + mod
    target = 8 + small
    if a == b == 1 or (t < target and not a == b == 6):
        return f"2d6[{a},{b}]{mod:+d} = {t} / 目標{target} → 外れ"
    hits = sum(random.randint(1, 3) for _ in range(guns)) // 2
    crit = a == b == 6 or t >= target + 4
    if crit:
        hits *= 2
    crew = max(0, hits // 3 + random.randint(0, 1))
    note = "（会心か大きく上回った：倍。帆柱か舵を狙うならここで壊れる）" if crit else ""
    return f"2d6[{a},{b}]{mod:+d} = {t} / 目標{target} → 命中。船体 −{hits}、水夫 −{crew}{note}"


def board(n1, s1, n2, s2):
    def ratio_mod(a, b):
        r = a / max(1, b)
        return 3 if r >= 3 else 2 if r >= 2 else 1 if r >= 1.5 else 0
    m1 = s1 + ratio_mod(n1, n2)
    m2 = s2 + ratio_mod(n2, n1)
    a, b = d(), d()
    t1, t2 = sum(a) + m1, sum(b) + m2
    diff = abs(t1 - t2)
    if t1 == t2:
        l1 = max(1, round(n1 * 0.08))
        l2 = max(1, round(n2 * 0.08))
        res = "押し合い"
    elif t1 > t2:
        l2 = max(1, round(n2 * (0.08 + 0.04 * diff)))
        l1 = max(0, round(l2 * 0.4))
        res = "味方が押した"
    else:
        l1 = max(1, round(n1 * (0.08 + 0.04 * diff)))
        l2 = max(0, round(l1 * 0.4))
        res = "敵が押した"
    s = (f"味方 {n1}人 2d6{a}{m1:+d} = {t1}　敵 {n2}人 2d6{b}{m2:+d} = {t2} → {res}（差 {diff}）\n"
         f"  倒れた者：味方 {l1}、敵 {l2}　→ 残り 味方 {n1 - l1}、敵 {n2 - l2}")
    for side, n0, left in (("味方", n1, n1 - l1), ("敵", n2, n2 - l2)):
        if left <= n0 * 0.5:
            s += f"\n  {side}は半分を切った：士気の判定（胆＋指揮 目標9）か、降る"
    if t1 < t2 and diff >= 3:
        s += "\n  船長が先頭にいたなら fate を振る（危うさ 1）"
    return s


def flee(s1, n1, s2, n2):
    return vs(s1 // 2 + n1, s2 // 2 + n2) + "\n  こちらが勝てば離れられる。負ければもう一合"


def fate(body, danger):
    a, b = d()
    t = a + b + body - danger
    if a == b == 1 or t <= 3:
        r = "死ぬ"
    elif t <= 5:
        r = "重い傷（体力が半分になり、30日は甲板に立てない。後に残る傷を一つ）"
    elif t <= 7:
        r = "傷（体力 −1d6）"
    else:
        r = "無事"
    return f"2d6[{a},{b}]+体{body}−危うさ{danger} = {t} → {r}"


def opinion(push, trust):
    a, b = d()
    t = a + b + push
    if trust <= -20:
        t += 1
    s = "強く言う（引かない。押し切られたら不満が残る）" if t >= 10 else "はっきり言う（理由があれば引く）" if t >= 7 else "一言だけ（言わずに飲みこむこともある）"
    return f"2d6[{a},{b}]+押し{push}{' +1（信頼が低い）' if trust <= -20 else ''} = {t} → {s}"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    c = args[0]
    n = [int(x) for x in args[1:] if re.fullmatch(r"-?\d+", x)]
    if c == "check":
        out = check(n[0], n[1])
    elif c == "vs":
        out = vs(n[0], n[1])
    elif c == "gun":
        out = gun(n[0], n[1], n[2] if len(n) > 2 else 0)
    elif c == "board":
        out = board(*n[:4])
    elif c == "flee":
        out = flee(*n[:4])
    elif c == "fate":
        out = fate(n[0], n[1])
    elif c == "initiative":
        a, b = d()
        t = a + b + n[0]
        out = f"仕掛け 2d6[{a},{b}]+能動{n[0]} = {t} / 10 → {'仕掛ける（帳面の未着手から一つ実行）' if t >= 10 else '様子を見る'}"
    elif c == "opinion":
        out = opinion(n[0], n[1])
    elif c in ("policy", "pick"):
        k = n[0] if n else 6
        out = f"1〜{k} → {random.randint(1, k)}"
    else:
        out = roll_expr(c)
    print(out)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.datetime.now():%Y-%m-%d %H:%M}  dice.py {' '.join(args)}\n{out}\n")


if __name__ == "__main__":
    main()
