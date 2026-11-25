#!/usr/bin/env python3
"""世界の時計と暦（ヴェルデン）。PC が関わらなくても、世界はこれで進む。

時計の定義と状態：gm/時計.json
  各時計：id, 名前, 範囲（町／国／世界／人物／一行）, 目盛り, いま, 速さ（1日に進む確率 1〜6 の「d6でこれ以下」）,
          状態（動いている／止まっている／満ちた）, 満ちたら, 途中（目盛りごとに起きること {"2": "..."}）,
          関わる（クエストや人物の名前）

  python tools/world.py date                   … いまの日付
  python tools/world.py list [範囲]             … 動いている時計（範囲で絞れる）
  python tools/world.py day [n]                 … n日進める。時計を振り、町の出来事 2d6 と天気を振る
  python tools/world.py tick <id> [n]           … 物語の中の出来事で、時計を n 目盛り進める（マイナスで戻す）
  python tools/world.py set <id> 状態 止まっている … 時計の状態を変える
  python tools/world.py show <id>               … 一つの時計をくわしく

満ちた時計は「満ちた」になり、満ちたら の中身が出る。GM はそれを世界に起こす（PC が見ていなくても）。
"""
import json, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
F = ROOT / "gm" / "時計.json"
MONTHS = ["霜の月", "雪解けの月", "芽吹きの月", "花の月", "雨の月", "陽の月",
          "盛夏の月", "実りの月", "刈り入れの月", "落葉の月", "霧の月", "冬至の月"]
WEEK = ["月の日", "火の日", "水の日", "木の日", "金の日", "土の日", "聖日"]
WEATHER = {2: "嵐（外を行くのは危うい。川が増す）", 3: "大雨", 4: "雨", 5: "曇り・肌寒い", 6: "曇り", 7: "晴れ",
           8: "晴れ", 9: "薄曇り", 10: "霧（朝のうち。見通しが悪い）", 11: "からりと晴れ", 12: "季節はずれの空（雪・雷・妙な色の夕焼け。噂になる）"}


def load():
    return json.loads(F.read_text(encoding="utf-8"))


def save(d):
    F.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def datestr(day, year0):
    # day は 0 から。1年 = 12か月 × 30日
    y, r = divmod(day, 360)
    mo, dd = divmod(r, 30)
    return f"王国暦{year0 + y}年 {MONTHS[mo]} {dd + 1}日（{WEEK[day % 7]}）"


def bar(c):
    return "■" * c["いま"] + "□" * (c["目盛り"] - c["いま"])


def line(c):
    return f"[{c['id']}] {c['名前']}（{c['範囲']}） {bar(c)} {c['いま']}/{c['目盛り']} 速さ{c['速さ']}/6 {c['状態']}"


def advance(c, n, out):
    for _ in range(abs(n)):
        if n > 0 and c["いま"] < c["目盛り"]:
            c["いま"] += 1
            mid = c.get("途中", {}).get(str(c["いま"]))
            if mid:
                out.append(f"    ・{c['名前']} {c['いま']}目盛り：{mid}")
            if c["いま"] >= c["目盛り"]:
                c["状態"] = "満ちた"
                out.append(f"  ★満ちた：{c['名前']} → {c['満ちたら']}")
                break
        elif n < 0 and c["いま"] > 0:
            c["いま"] -= 1


def main(a):
    if not a:
        print(__doc__); return
    d = load()
    cmd = a[0]
    clocks = d["時計"]
    by = {c["id"]: c for c in clocks}
    if cmd == "date":
        print(datestr(d["日"], d["元年"]), f"｜始まりから {d['日'] - d['始まり'] + 1} 日目")
    elif cmd == "list":
        for c in clocks:
            if c["状態"] == "動いている" and (len(a) < 2 or c["範囲"] == a[1]):
                print(line(c))
    elif cmd == "show":
        c = by[a[1]]
        print(line(c)); print("  満ちたら：", c["満ちたら"])
        for k, v in sorted(c.get("途中", {}).items(), key=lambda t: int(t[0])):
            print(f"  {k}：{v}")
        if c.get("関わる"):
            print("  関わる：", "、".join(c["関わる"]))
    elif cmd == "tick":
        c = by[a[1]]; n = int(a[2]) if len(a) > 2 else 1
        out = []
        advance(c, n, out)
        print(line(c)); print("\n".join(out)); save(d)
    elif cmd == "set":
        by[a[1]][a[2]] = a[3]; save(d); print(line(by[a[1]]))
    elif cmd == "day":
        n = int(a[1]) if len(a) > 1 else 1
        for _ in range(n):
            d["日"] += 1
            out = [f"■ {datestr(d['日'], d['元年'])}"]
            w = random.randint(1, 6) + random.randint(1, 6)
            out.append(f"  天気 2d6={w}：{WEATHER[w]}")
            t1, t2 = random.randint(1, 6), random.randint(1, 6)
            out.append(f"  町の出来事 2d6={t1 + t2}（{t1},{t2}）→ gm/町の出来事表.md の {t1 + t2} を引く")
            for c in clocks:
                if c["状態"] != "動いている":
                    continue
                r = random.randint(1, 6)
                if r <= c["速さ"]:
                    out.append(f"  {c['名前']}：d6={r}≤{c['速さ']} 進む")
                    advance(c, 1, out)
            print("\n".join(out))
        save(d)
    else:
        print(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
