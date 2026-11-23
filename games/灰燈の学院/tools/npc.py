#!/usr/bin/env python3
"""NPC の値を振る。
  python3 tools/npc.py 才 3      … 才ある者・三年生（学院で二年過ごしたぶん伸ばす）
  才の段：凡（得意1・普通2・苦手3）／才（得意2・普通2・苦手2）／天才（得意3・普通2・苦手1）
  学年 n の者は、(n-1) 年ぶん伸ばす。一年に、各分野の印 6 つ、各能力の印 3 つとして数える
  （得意：印ごとに +1d10 ／ 普通：印ごとに 1d100 > 値なら +1d10 ／ 苦手：伸びない。能力は普通の伸び方）
"""
import random, sys
F = ['熱導', '動導', '光導', '癒導', '刻導', '識導']
A = ['体', '知恵', '心']
TIER = {'凡': (1, 2, 3), '才': (2, 2, 2), '天才': (3, 2, 1)}
d = lambda n: random.randint(1, n)

def grow_normal(v, marks):
    for _ in range(marks):
        if d(100) > v:
            v += d(10)
    return v

def make(tier='才', grade=1):
    g, n, w = TIER[tier]
    years = grade - 1
    base = {f: d(100) for f in F}
    order = sorted(F, key=lambda f: -base[f])
    apt = {f: ('得意' if i < g else '普通' if i < g + n else '苦手') for i, f in enumerate(order)}
    val = {}
    for f in F:
        v = base[f]
        m = 6 * years
        if apt[f] == '得意':
            v += sum(d(10) for _ in range(m))
        elif apt[f] == '普通':
            v = grow_normal(v, m)
        val[f] = v
    ab0 = {a: d(100) for a in A}
    ab = {a: grow_normal(ab0[a], 3 * years) for a in A}
    print(f"（{tier}・{grade}年生）")
    print("| 能力 | 振った値 | 値 |\n|---|---|---|")
    for a in A:
        print(f"| {a} | {ab0[a]} | {ab[a]} |")
    print("\n| 分野 | 適性 | 振った値 | 値 |\n|---|---|---|---|")
    for f in order:
        print(f"| {f} | {apt[f]} | {base[f]} | {val[f]} |")

if __name__ == "__main__":
    a = sys.argv[1:]
    make(a[0] if a else '才', int(a[1]) if len(a) > 1 else 1)
