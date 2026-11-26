#!/usr/bin/env python3
"""海を作る（リアナ）。遊ぶ前に一度だけ動かす。

  python tools/gen.py preview      … 陸と海の形だけを画面に出す（作り直しの確認用）
  python tools/gen.py build        … gm/海.json を書き出す（すでにあれば止まる）
  python tools/gen.py build --force

陸の大きな形は手で決め、海岸の細かい形だけを乱数（種 SEED）で崩す。
港・発見物・海域は、下の表（PORTS / FINDS / ZONES）に手で書いたものだけを置く。
遊んでいる最中に、この表へ都合のいいものを足さない（足すなら、遊ぶ前に書いて build し直す）。
"""
import json, math, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "gm" / "海.json"
W, H = 96, 48
SEED = 1472

# ---------------------------------------------------------------- 陸の形
# (中心x, 中心y, 半径x, 半径y) の楕円を足し引きする。+ が陸、- が海。
LAND = [
    # 旧大陸（北東）
    ("+", 74, 6, 26, 14),
    ("+", 54, 8, 5, 9),
    ("+", 88, 20, 9, 5),          # 東の半島の付け根
    ("+", 86, 26, 4, 5),          # 東の半島（香の道の港がある）
    # 内海を掘る
    ("-", 72, 11, 16, 4.2),
    ("-", 60, 12.4, 6, 1.6),
    ("-", 53.5, 12.6, 3.5, 0.9),  # 狭間の海峡
    # 南の大陸
    ("+", 64, 21, 18, 4),
    ("+", 57, 27, 14, 7),
    ("+", 48, 25, 4, 3.5),          # 西に張り出す角
    ("+", 57, 34, 9, 7),
    ("+", 57, 40, 5, 4),        # 嵐の岬へ細る
    ("+", 66, 31, 5, 6),
    # 新大陸（西）
    ("+", 0, 14, 6, 12),
    ("+", 3, 30, 5, 10),
    ("+", 1, 42, 5, 6),
    ("+", 7, 22, 2.5, 2),
    # 翠の諸島（西の中ほど）
    ("+", 18, 23, 2.2, 1.2),
    ("+", 21.5, 25, 1.6, 1.0),
    ("+", 24.5, 26.5, 1.2, 0.8),
    ("+", 16, 20.5, 1.0, 0.8),
    # 霧の諸島（大洋のまんなか、北寄り）
    ("+", 31, 9, 1.3, 0.9),
    ("+", 34, 10.5, 0.9, 0.7),
    ("+", 29, 11, 0.8, 0.6),
    # 火の島（南の大陸の沖）
    ("+", 38, 19, 1.2, 0.9),
    ("+", 40.5, 20.5, 0.8, 0.7),
    # 東の海の島々
    ("+", 92, 38, 1.6, 1.1),      # 香料の島（大）
    ("+", 89, 41, 1.0, 0.8),
    ("+", 94.5, 41, 0.8, 0.7),
    ("+", 80, 33, 2.0, 1.2),      # 東の海の大きな島
    # 遠い南の孤島
    ("+", 38, 39, 0.9, 0.7),
]


def noise_field(seed):
    rnd = random.Random(seed)
    grid = {}

    def val(ix, iy, s):
        k = (ix, iy, s)
        if k not in grid:
            grid[k] = rnd.random() * 2 - 1
        return grid[k]

    def smooth(x, y, s):
        x0, y0 = math.floor(x), math.floor(y)
        fx, fy = x - x0, y - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = val(x0, y0, s) * (1 - fx) + val(x0 + 1, y0, s) * fx
        b = val(x0, y0 + 1, s) * (1 - fx) + val(x0 + 1, y0 + 1, s) * fx
        return a * (1 - fy) + b * fy

    def f(x, y):
        return 0.6 * smooth(x / 4, y / 4, 1) + 0.3 * smooth(x / 2, y / 2, 2) + 0.15 * smooth(x, y, 3)
    return f


def make_land():
    nz = noise_field(SEED)
    land = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            v = 0.0
            inside = False
            for sign, cx, cy, rx, ry in LAND:
                d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                small = rx < 3
                jitter = nz(x, y) * (0.15 if small else 0.45)
                if d + jitter < 1:
                    inside = sign == "+"
            land[y][x] = inside
    return land


# ---------------------------------------------------------------- 港
# 名, x, y（陸のマス。build で近い海岸に寄せる）, 国, 知られているか, 中身は PORTS_DATA（gm/港.md の元）
PORTS = [
    # 名前,        x,  y, 国・人々,        始めから知られているか
    ("リアナ",     50, 10, "リアナ王国",    True),
    ("カボ・ベル", 49, 16, "リアナ王国",    True),
    ("ノルテ",     51, 5,  "リアナ王国",    True),
    ("フロイン",   52, 1,  "フロイン同盟",  True),
    ("ヴェスカ",   78, 7,  "ヴェスカ共和国", True),
    ("ドルミ",     66, 8,  "ヴェスカ共和国", True),
    ("ハッサラ",   82, 15, "サルハド朝",    True),
    ("サルハド",   69, 15, "サルハド朝",    True),
    # 南の大陸の西岸（知られていない）
    ("ガロエ",     38, 19, "火の島の人々",   False),
    ("ザムル",     44, 27, "ザムルの王国",   False),
    ("トゥバ",     48, 33, "トゥバの町々",   False),
    ("ケンバ",     51, 40, "ケンバの人々",   False),
    # 南の大陸の東岸と東の海
    ("ミレジ",     64, 38, "ミレジの港市",   False),
    ("アスパル",   86, 29, "東の海の商人",   False),
    ("ヨルカ",     92, 38, "香料の島々",     False),
    ("バンタ",     80, 33, "東の海の商人",   False),
    # 新大陸と翠の諸島
    ("トラロ",     18, 23, "翠の諸島の人々", False),
    ("イシュカ",   7, 30,  "イシュカの国",   False),
    ("ナワン",     6, 12,  "北の森の人々",   False),
]

# ---------------------------------------------------------------- 海域（風と危なさ）
# 風の帯は緯度（y）で決まる。東の海（x>=72, y>=22）だけは季節風。
# danger：毎日の出会いの振りに足す。storm：嵐の起きやすさ（季節は gm/海域.md）
ZONES = [
    # 名,           x0, y0, x1, y1, danger, storm
    ("狭間の海",     46, 9, 58, 16, 2, 0),
    ("内海",         56, 5, 90, 17, 1, 0),
    ("翠の諸島の海", 12, 18, 28, 30, 2, 2),
    ("藻の海",       22, 13, 32, 19, 0, 0),
    ("嵐の岬の沖",   48, 41, 68, 48, 1, 2),
    ("東の海",       72, 22, 96, 48, 1, 1),
    ("北の大洋",     0, 0, 46, 13, 0, 1),
]

# ---------------------------------------------------------------- 発見物
# 名, x, y, 種類, 値（報告したときの重み 1〜10）, 見つけ方
#   sight：そのマスが見えれば見つかる（岬・海峡・島の形）
#   land ：隣のマスで上陸して調べると見つかる（遺跡・生き物・植物）
FINDS = [
    ("霧の諸島",           31, 9,  "地理", 4, "sight"),
    ("火の島",             38, 19, "地理", 3, "sight"),
    ("西に張り出す角",     43, 25, "地理", 3, "sight"),
    ("黒い砂の河口",       46, 31, "地理", 3, "sight"),
    ("嵐の岬",             57, 44, "地理", 10, "sight"),
    ("東の海の入口",       69, 40, "地理", 6, "sight"),
    ("東の半島の先",       86, 31, "地理", 5, "sight"),
    ("香料の島々",         92, 38, "地理", 9, "sight"),
    ("翠の諸島",           18, 23, "地理", 7, "sight"),
    ("西の大陸の岸",       8, 22,  "地理", 10, "sight"),
    ("北の森の湾",         8, 11,  "地理", 5, "sight"),
    ("南の孤島",           38, 39, "地理", 4, "sight"),
    ("藻の海",             27, 16, "地理", 4, "sight"),
    ("火の山の石の顔",     40, 20, "遺跡", 4, "land"),
    ("霧の諸島の大鳥",     34, 10, "生き物", 3, "land"),
    ("ザムルの金の鉱脈",   45, 26, "品物", 6, "land"),
    ("黒い砂の河馬",       47, 31, "生き物", 3, "land"),
    ("トゥバの星の塔",     49, 34, "遺跡", 5, "land"),
    ("嵐の岬の岩絵",       56, 42, "遺跡", 5, "land"),
    ("翠の諸島の甘い葦",   21, 25, "品物", 6, "land"),
    ("火を吐く山",         4, 34,  "地理", 4, "land"),
    ("イシュカの段の都",   6, 29,  "遺跡", 8, "land"),
    ("北の森の大鹿",       5, 13,  "生き物", 3, "land"),
    ("南の孤島の巨亀",     38, 39, "生き物", 4, "land"),
    ("東の島の極楽鳥",     80, 33, "生き物", 5, "land"),
    ("沈んだ大船",         25, 17, "遺跡", 6, "sight"),
]


def neighbors8(x, y):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    yield nx, ny


def build_map():
    land = make_land()
    rnd = random.Random(SEED + 7)
    cells = [["~"] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if land[y][x]:
                cells[y][x] = "#"
    # 沿岸の海（陸に接する海）
    for y in range(H):
        for x in range(W):
            if cells[y][x] == "~" and any(land[ny][nx] for nx, ny in neighbors8(x, y)):
                cells[y][x] = "."
    # 浅瀬・暗礁：沿岸のうち、島のまわりと決めた場所に乱数で
    for y in range(H):
        for x in range(W):
            if cells[y][x] == ".":
                z = zone_of(x, y)
                p = 0.18 if z in ("翠の諸島の海", "嵐の岬の沖") else 0.05
                if z == "内海":
                    p = 0.02
                if rnd.random() < p:
                    cells[y][x] = ":"
    # 藻の海
    for y in range(14, 19):
        for x in range(23, 32):
            if cells[y][x] == "~" and ((x - 27.5) / 4.6) ** 2 + ((y - 16) / 2.6) ** 2 < 1:
                cells[y][x] = "m"
    return land, cells


def zone_of(x, y):
    for name, x0, y0, x1, y1, d, s in ZONES:
        if x0 <= x < x1 and y0 <= y < y1:
            return name
    return "大洋"


def snap_port(cells, x, y):
    """港を、海に接する陸のマスに寄せる。"""
    best = None
    for yy in range(max(0, y - 4), min(H, y + 5)):
        for xx in range(max(0, x - 4), min(W, x + 5)):
            if cells[yy][xx] == "#" and any(cells[ny][nx] in ".:" for nx, ny in neighbors8(xx, yy)):
                d = abs(xx - x) + abs(yy - y)
                if best is None or d < best[0]:
                    best = (d, xx, yy)
    if not best:
        sys.exit(f"港を置けない：{x},{y}")
    return best[1], best[2]


def snap_find(cells, x, y, kind):
    want = "#" if kind == "land" else None
    best = None
    for yy in range(max(0, y - 3), min(H, y + 4)):
        for xx in range(max(0, x - 3), min(W, x + 4)):
            c = cells[yy][xx]
            ok = (c == "#" and any(cells[ny][nx] in ".:" for nx, ny in neighbors8(xx, yy))) if want else True
            if ok:
                d = abs(xx - x) + abs(yy - y)
                if best is None or d < best[0]:
                    best = (d, xx, yy)
    return best[1], best[2]


def preview(cells, ports=None, finds=None):
    marks = {}
    for p in ports or []:
        marks[(p["x"], p["y"])] = "P"
    for f in finds or []:
        marks.setdefault((f["x"], f["y"]), "*")
    print("    " + "".join(str(x // 10) for x in range(W)))
    print("    " + "".join(str(x % 10) for x in range(W)))
    for y in range(H):
        print(f"{y:3d} " + "".join(marks.get((x, y), cells[y][x]) for x in range(W)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    land, cells = build_map()
    ports = []
    for name, x, y, nation, known in PORTS:
        px, py = snap_port(cells, x, y)
        ports.append({"name": name, "x": px, "y": py, "nation": nation, "known": known})
    finds = []
    for name, x, y, kind, value, how in FINDS:
        fx, fy = snap_find(cells, x, y, how)
        finds.append({"name": name, "x": fx, "y": fy, "kind": kind, "value": value, "how": how})
    if cmd == "preview":
        preview(cells, ports, finds)
        return
    if cmd == "build":
        if OUT.exists() and "--force" not in sys.argv:
            sys.exit(f"{OUT} はもうある。作り直すなら --force（遊び始めたあとは作り直さない）")
        zones = [{"name": n, "x0": a, "y0": b, "x1": c, "y1": d, "danger": dg, "storm": st}
                 for n, a, b, c, d, dg, st in ZONES]
        data = {"seed": SEED, "w": W, "h": H, "rows": ["".join(r) for r in cells],
                "ports": ports, "finds": finds, "zones": zones}
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"書き出した：{OUT}")
        preview(cells, ports, finds)


if __name__ == "__main__":
    main()
