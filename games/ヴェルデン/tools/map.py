#!/usr/bin/env python3
"""マス目の地図を管理する（ヴェルデン）。

地図の定義：gm/地図/<名前>.md の中の ```map / ```legend / ```events / ```meta ブロック
いまの状態：gm/地図/状態.json（位置・見えたマス・訪ねた回数・開けた扉・歩いた刻）

  python tools/map.py list                       … 地図の一覧と、いまいる地図
  python tools/map.py enter 迷宮一層 [x y]        … その地図に入る（座標を省くと @ の位置）
  python tools/map.py move nnee                  … 一歩ずつ動く（n北 s南 e東 w西、n3 のように数も可）
  python tools/map.py goto 12 5                  … 見えているマスだけを通って、最短で行く（二度目以降の道の省略用）
  python tools/map.py view [名前] [--gm]          … 地図を出す（--gm で隠れたところも全部）
  python tools/map.py where                      … いまの位置と、まわりのマス
  python tools/map.py open 10 4                  … 閉ざされた扉などを「開いた」にする（以後通れる）
  python tools/map.py close 10 4                 … 開いたものを閉じる
  python tools/map.py clear 10 4                 … その場所の出来事を「済み」にする（表示が小文字になる）
  python tools/map.py reveal 10 4 [半径]          … 地図・噂・高所からの眺めなどで、マスを見えたことにする
  python tools/map.py public [名前]               … 瀬島用の地図（地図/<名前>.md）を書き出す
  python tools/map.py reset 名前                  … その地図の状態を消す（作り直したとき）

止まるところ：壁・閉じた扉の前、出来事のマスに初めて入ったとき、legend で stop のついたマス。
訪ねたことのある出来事のマスは止まらず、「既訪」として通過を知らせる。
"""
import json, pathlib, re, sys
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAPDIR = ROOT / "gm" / "地図"
STATE = MAPDIR / "状態.json"
PUBDIR = ROOT / "地図"
DIRS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
DIRNAME = {"n": "北", "s": "南", "e": "東", "w": "西"}


def blocks(text, name):
    m = re.search(r"```" + name + r"\n(.*?)```", text, re.S)
    return m.group(1).rstrip("\n").split("\n") if m else []


class Map:
    def __init__(self, name):
        self.name = name
        path = MAPDIR / f"{name}.md"
        if not path.exists():
            sys.exit(f"地図がない：{path}")
        text = path.read_text(encoding="utf-8")
        self.grid = [list(l) for l in blocks(text, "map")]
        self.h = len(self.grid)
        self.w = max(len(r) for r in self.grid)
        for r in self.grid:
            r += [" "] * (self.w - len(r))
        self.legend = {}
        for l in blocks(text, "legend"):
            if not l.strip() or l.startswith("//"):
                continue
            p = l.split()
            ch, label, cost, disp = p[0], p[1], int(p[2]), p[3]
            self.legend[ch] = {"label": label, "cost": cost, "disp": disp, "stop": "stop" in p[4:],
                               "opaque": "opaque" in p[4:] or (cost == 0 and "clear" not in p[4:]),
                               "door": "door" in p[4:]}
        self.events = {}
        for l in blocks(text, "events"):
            if l.strip() and not l.startswith("//"):
                k, v = l.split(None, 1)
                self.events[k] = v
        self.meta = {}
        for l in blocks(text, "meta"):
            if l.strip() and not l.startswith("//"):
                k, v = l.split(None, 1)
                self.meta[k] = v
        self.light = int(self.meta.get("light", 1))
        self.unit = self.meta.get("unit", "刻")
        self.check_every = int(self.meta.get("check_every", 0))
        self.start = None
        for y, r in enumerate(self.grid):
            for x, c in enumerate(r):
                if c == "@":
                    self.start = (x, y)
                    r[x] = self.meta.get("start_tile", ".")

    def ch(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.grid[y][x]
        return " "

    def info(self, c):
        if c in self.events:
            return {"label": self.events[c], "cost": int(self.meta.get("event_cost", 1)), "disp": "?",
                    "stop": True, "opaque": False, "door": False}
        return self.legend.get(c, {"label": "外", "cost": 0, "disp": " ", "stop": False, "opaque": True, "door": False})


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"current": None, "maps": {}}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def mstate(st, name):
    return st["maps"].setdefault(name, {"pos": None, "seen": [], "visits": {}, "opened": [], "cleared": [], "time": 0})


def key(x, y):
    return f"{x},{y}"


def cost_at(m, ms, x, y):
    c = m.ch(x, y)
    i = m.info(c)
    if key(x, y) in ms["opened"]:
        return max(1, i["cost"]) if i["cost"] else 1
    return i["cost"]


def opaque_at(m, ms, x, y):
    i = m.info(m.ch(x, y))
    if key(x, y) in ms["opened"]:
        return False
    return i["opaque"] or i["door"]


def line_clear(m, ms, x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x1 > x0 else -1), (1 if y1 > y0 else -1)
    err, x, y = dx - dy, x0, y0
    while (x, y) != (x1, y1):
        if (x, y) != (x0, y0) and opaque_at(m, ms, x, y):
            return False
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x += sx
        if e2 < dx:
            err += dx; y += sy
    return True


def look(m, ms, x, y, r=None):
    r = m.light if r is None else r
    seen = set(ms["seen"])
    new = []
    for yy in range(y - r, y + r + 1):
        for xx in range(x - r, x + r + 1):
            if 0 <= xx < m.w and 0 <= yy < m.h and line_clear(m, ms, x, y, xx, yy):
                k = key(xx, yy)
                if k not in seen:
                    seen.add(k); new.append((xx, yy))
    ms["seen"] = sorted(seen)
    return new


def disp(m, ms, x, y, gm=False, pos=None):
    if pos == (x, y):
        return "@"
    k = key(x, y)
    if not gm and k not in ms["seen"]:
        return " "
    c = m.ch(x, y)
    if c in m.events:
        if gm:
            return c.lower() if k in ms["cleared"] else c
        if k in ms["cleared"]:
            return c.lower()
        if ms["visits"].get(k) or m.meta.get("events_known") == "yes":
            return c
        return "?"
    i = m.info(c)
    if k in ms["opened"] and "open_disp" in m.meta:
        return m.meta["open_disp"]
    return i["disp"]


def render(m, ms, gm=False):
    pos = tuple(ms["pos"]) if ms["pos"] else None
    tens = "    " + "".join(str(x // 10) if x % 10 == 0 else " " for x in range(m.w))
    ones = "    " + "".join(str(x % 10) for x in range(m.w))
    out = [tens, ones]
    for y in range(m.h):
        out.append(f"{y:>3} " + "".join(disp(m, ms, x, y, gm, pos) for x in range(m.w)))
    shown = set()
    for y in range(m.h):
        for x in range(m.w):
            d = disp(m, ms, x, y, gm, pos)
            if d != " ":
                shown.add((d, m.ch(x, y)))
    leg = []
    for ch, i in m.legend.items():
        if any(d == i["disp"] for d, _ in shown) and not any(x.startswith(i["disp"] + " ") for x in leg):
            leg.append(f"{i['disp']} {i['label']}")
    if "open_disp" in m.meta and any(d == m.meta["open_disp"] for d, _ in shown):
        leg.append(f"{m.meta['open_disp']} 開いた扉・通れるようになった所")
    evs = []
    for d, c in sorted(shown):
        if c in m.events and d != "?":
            evs.append(f"{d} {m.events[c].split('｜')[0]}")
    if any(d == "?" for d, _ in shown):
        evs.append("? まだ確かめていない何か")
    return "\n".join(out), leg, evs


def tstr(m, t):
    mins = m.meta.get("minutes")
    if not mins:
        return f"{t}{m.unit}"
    total = t * int(mins)
    h, mm = divmod(total, 60)
    return (f"{h}時間" if h else "") + (f"{mm}分" if mm else "") or "0分"


def report_pos(m, ms):
    x, y = ms["pos"]
    c = m.ch(x, y)
    around = []
    for d, (dx, dy) in DIRS.items():
        cc = m.ch(x + dx, y + dy)
        k = key(x + dx, y + dy)
        i = m.info(cc)
        known = ms["visits"].get(k) or m.meta.get("events_known") == "yes"
        lab = i["label"] if cc not in m.events else ("出来事（" + m.events[cc].split("｜")[0] + "）" if known else "何かある")
        if k in ms["opened"]:
            lab += "（開いている）"
        around.append(f"{DIRNAME[d]}:{lab}")
    here = m.info(c)["label"] if c not in m.events else m.events[c]
    return f"[{m.name}] ({x},{y}) {here}｜まわり " + " / ".join(around) + f"｜歩いた {tstr(m, ms['time'])}"


def tick(m, ms, cost, log):
    before = ms["time"]
    ms["time"] += cost
    if m.check_every and before // m.check_every != ms["time"] // m.check_every:
        log.append(f"  ＊ {tstr(m, ms['time'])}：遭遇・時の判定をする頃（{tstr(m, m.check_every)}ごと）")


def step_into(m, ms, nx, ny, log, quiet_known=False):
    """1マス入る。止まるべきなら True を返す。"""
    c = m.ch(nx, ny)
    i = m.info(c)
    k = key(nx, ny)
    co = cost_at(m, ms, nx, ny)
    if co == 0:
        log.append(f"  ({nx},{ny}) {i['label']}：通れない")
        return "blocked"
    ms["pos"] = [nx, ny]
    if i["door"] and k not in ms["opened"]:
        ms["opened"].append(k)  # 扉は、くぐれば開いたままになる（閉めるなら close）
    tick(m, ms, co, log)
    new = look(m, ms, nx, ny)
    first = not ms["visits"].get(k)
    ms["visits"][k] = ms["visits"].get(k, 0) + 1
    newev = [(x, y) for x, y in new if m.ch(x, y) in m.events]
    stop = False
    if c in m.events:
        if first and k not in ms["cleared"]:
            log.append(f"  → ({nx},{ny}) 出来事【{c}】{m.events[c]}  ← 初めて。ここで止まる")
            stop = True
        else:
            log.append(f"  → ({nx},{ny}) 既訪【{c}】{m.events[c].split('｜')[0]}（{ms['visits'][k]}回目。省略してよい）")
    elif i["stop"] and first:
        log.append(f"  → ({nx},{ny}) {i['label']}（初めて。止まる）")
        stop = True
    elif i["stop"] and k not in ms["cleared"]:
        log.append(f"  → ({nx},{ny}) {i['label']}を通る（罠なら、外していなければまた発動する。外したら clear）")
    elif i["door"] and k not in ms["opened"]:
        log.append(f"  → ({nx},{ny}) {i['label']}：扉の前を抜けた")
    for x, y in newev:
        if not ms["visits"].get(key(x, y)):
            log.append(f"  ・({x},{y}) に何かが見える（? のマス）")
    return "stop" if stop else "ok"


def parse_moves(s):
    out = []
    for d, n in re.findall(r"([nsew])(\d*)", s.lower()):
        out += [d] * (int(n) if n else 1)
    return out


def main(a):
    if not a:
        print(__doc__); return
    st = load_state()
    cmd = a[0]
    if cmd == "list":
        for p in sorted(MAPDIR.glob("*.md")):
            mark = "← いま" if st.get("current") == p.stem else ""
            print(p.stem, mark)
        return
    if cmd == "enter":
        m = Map(a[1]); ms = mstate(st, m.name)
        if len(a) >= 4:
            ms["pos"] = [int(a[2]), int(a[3])]
        elif ms["pos"] is None:
            if not m.start:
                sys.exit("@ のない地図には座標を渡す")
            ms["pos"] = list(m.start)
        st["current"] = m.name
        look(m, ms, *ms["pos"])
        k = key(*ms["pos"]); ms["visits"][k] = ms["visits"].get(k, 0) + 1
        save_state(st); print(report_pos(m, ms)); return
    if cmd == "reset":
        st["maps"].pop(a[1], None)
        if st.get("current") == a[1]:
            st["current"] = None
        save_state(st); print("消した：", a[1]); return
    name = st.get("current")
    if cmd in ("view", "public") and len(a) > 1 and not a[1].startswith("--"):
        name = a[1]
    if not name:
        sys.exit("まだどの地図にも入っていない（enter で入る）")
    m = Map(name); ms = mstate(st, name)
    if cmd == "move":
        log = []
        for d in parse_moves("".join(a[1:])):
            dx, dy = DIRS[d]
            x, y = ms["pos"]
            r = step_into(m, ms, x + dx, y + dy, log)
            if r == "blocked":
                break
            if r == "stop":
                break
        print("\n".join(log)); print(report_pos(m, ms))
    elif cmd == "goto":
        tx, ty = int(a[1]), int(a[2])
        sx, sy = ms["pos"]
        seen = set(ms["seen"])
        prev = {(sx, sy): None}
        dist = {(sx, sy): 0}
        import heapq
        pq = [(0, sx, sy)]
        while pq:
            dd, x, y = heapq.heappop(pq)
            if (x, y) == (tx, ty):
                break
            if dd > dist[(x, y)]:
                continue
            for dx, dy in DIRS.values():
                nx, ny = x + dx, y + dy
                if key(nx, ny) not in seen:
                    continue
                co = cost_at(m, ms, nx, ny)
                if co == 0:
                    continue
                nk = (nx, ny)
                if nk not in dist or dd + co < dist[nk]:
                    dist[nk] = dd + co; prev[nk] = (x, y); heapq.heappush(pq, (dd + co, nx, ny))
        if (tx, ty) not in prev:
            sys.exit("見えているマスだけでは、そこへ行けない")
        path = []
        cur = (tx, ty)
        while cur != (sx, sy):
            path.append(cur); cur = prev[cur]
        path.reverse()
        log = [f"  道のり {len(path)}マス"]
        for nx, ny in path:
            r = step_into(m, ms, nx, ny, log)
            if r != "ok":
                log.append("  （ここで止まった）"); break
        print("\n".join(log)); print(report_pos(m, ms))
    elif cmd == "view":
        g, leg, evs = render(m, ms, gm="--gm" in a)
        print(g); print("凡例：" + "　".join(leg))
        if evs:
            print("場所：" + "　".join(evs))
        if ms["pos"]:
            print(report_pos(m, ms))
    elif cmd == "where":
        print(report_pos(m, ms))
    elif cmd in ("open", "close", "clear"):
        k = key(int(a[1]), int(a[2]))
        lst = ms["opened"] if cmd != "clear" else ms["cleared"]
        if cmd == "close":
            if k in lst: lst.remove(k)
        elif k not in lst:
            lst.append(k)
        if cmd == "open" and ms["pos"]:
            look(m, ms, *ms["pos"])
        save_state(st); print(cmd, k, "済"); return
    elif cmd == "reveal":
        r = int(a[3]) if len(a) > 3 else 0
        x, y = int(a[1]), int(a[2])
        seen = set(ms["seen"])
        for yy in range(y - r, y + r + 1):
            for xx in range(x - r, x + r + 1):
                if 0 <= xx < m.w and 0 <= yy < m.h:
                    seen.add(key(xx, yy))
        ms["seen"] = sorted(seen)
    elif cmd == "public":
        g, leg, evs = render(m, ms)
        PUBDIR.mkdir(exist_ok=True)
        body = [f"# {m.name}（瀬島の地図）", "", m.meta.get("public_note", ""), "", "```", g, "```", "",
                "凡例：" + "　".join(leg)]
        if evs:
            body += ["", "場所：", *[f"- {e}" for e in evs]]
        if ms["pos"]:
            body += ["", f"いまの位置：({ms['pos'][0]},{ms['pos'][1]})　歩いた {tstr(m, ms['time'])}"]
        (PUBDIR / f"{m.name}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
        print("書き出した：", PUBDIR / f"{m.name}.md")
    save_state(st)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
