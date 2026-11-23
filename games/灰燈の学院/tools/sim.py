#!/usr/bin/env python3
"""決まりを試すための見積もり（遊びには使わない）"""
import random
d = lambda n: random.randint(1, n)

def result(v, div):
    r = d(100)
    if r >= 96: return '大失敗'
    if div == 1 and r <= max(1, v // 5): return '会心'
    if r <= v // div: return '成功'
    if div == 1 and r <= v + 10: return '紙一重'
    return '失敗'

print('■ 成功の見こみ（%）　簡単＝値以下 ／ 普通＝1/2 ／ 至難＝1/5。大失敗 96〜100 は常に')
print('| 値 | 簡単：会心 / 成功 / 紙一重 | 普通：成功 | 至難：成功 |')
print('|---|---|---|---|')
N = 20000
for v in (15, 30, 50, 65, 82, 100, 150, 240):
    c = {}
    for _ in range(N):
        k = result(v, 1); c[k] = c.get(k, 0) + 1
    h = sum(result(v, 2) == '成功' for _ in range(N))
    e = sum(result(v, 5) == '成功' for _ in range(N))
    p = lambda k: round(100 * c.get(k, 0) / N)
    print(f"| {v} | {p('会心')} / {p('成功')} / {p('紙一重')} | {round(100*h/N)} | {round(100*e/N)} |")

def grow(v, apt, marks):
    for _ in range(marks):
        if apt == '得意': v += d(10)
        elif apt == '普通' and d(100) > v: v += d(10)
    return v

print('\n■ 四年（十二学期）の伸びの見こみ：一学期に印いくつで、卒業のときいくつになるか（千回の平均）')
for marks in (2, 4, 6):
    row = []
    for apt, v0 in (('得意', 82), ('得意', 65), ('普通', 39), ('普通', 32)):
        avg = sum(grow(v0, apt, marks * 12) for _ in range(1000)) / 1000
        row.append(f"{apt}{v0}→{round(avg)}")
    print(f"一学期に印 {marks}：", '、'.join(row))
