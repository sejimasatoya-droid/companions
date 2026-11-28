# 宵送り 釣り合いの確かめ（GM用・簡略モデル）
import random, sys

PLACES = ["港", "汐見荘", "神社", "診療所", "分校跡", "灯台", "浜"]
# 16コマ: 日d(0-3) x 刻t(朝昼夕夜)
def S(*xs): return list(xs)
BASE = {
 "凪":   S("汐見荘","浜","汐見荘","汐見荘", "汐見荘","分校跡","汐見荘","汐見荘", "分校跡","神社","汐見荘","汐見荘", "汐見荘","神社","浜","浜"),
 "千鶴": S(*(["汐見荘"]*15), "浜"),
 "宗一郎": S("神社","神社","神社","神社", "神社","神社","港","神社", "神社","神社","神社","神社", "神社","神社","浜","浜"),
 "久世": S("診療所","診療所","診療所","汐見荘", "診療所","港","診療所","汐見荘", "診療所","診療所","診療所","診療所", "診療所","診療所","診療所","浜"),
 "一真": S("港","港","港","汐見荘", "港","港","港","汐見荘", "港","港","港","港", "港","港","浜","浜"),
 "紗英": S("港","神社","汐見荘","汐見荘", "灯台","診療所","港","汐見荘", "分校跡","神社","港","灯台", "汐見荘","分校跡","浜","浜"),
}
DEV = 0.10

def chk(r, ab, mod=0):
    return r.randint(1,6)+r.randint(1,6)+ab+mod >= 8

def run(plan, r, ab):
    """plan: dict slot -> (place, intent). 戻り値: 惨事か, 真相に必要な手がかり数"""
    loc = {n: [p if r.random() > DEV else r.choice(PLACES) for p in BASE[n]] for n in BASE}
    st = dict(proof=False, chizuru_hurt=False, record="clinic", kuze_keeps=False,
              incited=False, dissuaded=False, priest_alarm=False, alert=False,
              exposed=False, dead=set(), trust={n:0 for n in BASE}, clues=set(), seijima_dead=False,
              kazuma_letter_seen=False, luggage=False)
    def here(n, s): return loc[n][s]
    def sae_free(): return not st["exposed"]
    for s in range(16):
        place, intent = plan.get(s, (r.choice(PLACES), "talk"))
        # 瀬島の会話: その場にいる者と信頼+1（話す判定）
        for n in BASE:
            if here(n, s) == place and n != "紗英" and intent in ("talk","guard","watch") and chk(r, ab["話す"]):
                st["trust"][n] = min(3, st["trust"][n]+1)
        if intent == "search_sae" and here("紗英", s) != "汐見荘" and place == "汐見荘":
            if chk(r, ab["忍ぶ"]):
                st["luggage"] = True
                if chk(r, ab["観る"]): st["clues"].add("本名")
            else:
                if r.random() < .5: st["alert"] = True
        if intent == "letter" and place == here("一真", s) and st["trust"]["一真"] >= 1 and chk(r, ab["話す"]):
            st["kazuma_letter_seen"] = True
        if st["luggage"] and st["kazuma_letter_seen"]: st["clues"].add("便箋")
        if intent == "warn_kuze" and place == here("久世", s) and st["trust"]["久世"] >= 1 and chk(r, ab["話す"]):
            st["kuze_keeps"] = True
            if r.random() < .2: st["priest_alarm"] = True
        if intent == "expose" and len(st["clues"]) >= 2:
            witnesses = [n for n in BASE if n not in ("紗英",) and here(n, s) == place and st["trust"][n] >= 1]
            if here("紗英", s) == place and len(witnesses) >= 2 and chk(r, ab["話す"]):
                st["exposed"] = True
            elif r.random() < .5: st["alert"] = True
        if intent == "dissuade" and place == here("一真", s) and st["incited"] and st["trust"]["一真"] >= 2:
            mod = 1 if ({"便箋","港で見た"} & st["clues"]) else -3
            if chk(r, ab["話す"], mod): st["dissuaded"] = True
        if intent == "retrieve" and place == "港" and st["record"] == "boat":
            if chk(r, ab["忍ぶ"]): st["record"] = "seijima"
            else: st["trust"]["一真"] = max(0, st["trust"]["一真"]-1)

        # ---- 事件 ----
        sae_here = here("紗英", s)
        guard = (place == sae_here)
        if s == 2 and sae_free() and not st["proof"]:      # 一日目夕 千鶴の部屋
            if place == "汐見荘" and intent == "guard":
                if r.random() < .3: st["alert"] = True
            else:
                st["proof"] = True
                if here("千鶴", s) == "汐見荘" and r.random() < .7: st["chizuru_hurt"] = True
        if s in (7, 12) and sae_free() and not st["proof"]: # 再挑戦
            if place == "汐見荘" and intent == "guard": pass
            elif r.random() < .6: st["proof"] = True
        if s == 5 and sae_free() and st["record"] == "clinic":  # 二日目昼 盗み
            if st["kuze_keeps"]: pass
            elif place == "診療所":
                if chk(r, ab["観る"]): st["clues"].add("診療所で見た")
                if r.random() < .5: st["alert"] = True
            elif here("久世", s) != "診療所" and r.random() < .9: st["record"] = "sae"
        if s == 7 and sae_free() and st["record"] == "clinic" and not st["kuze_keeps"]:
            if not (place == "診療所") and r.random() < .5: st["record"] = "sae"
        if s in (6, 7) and sae_free() and st["record"] == "sae":   # 舟に置く
            if place == "港" and chk(r, ab["観る"]): st["clues"].add("港で見た")
            st["record"] = "boat"
        if s == 8 and st["record"] == "boat":   # 三日目朝 一真が見つける
            st["incited"] = True; st["record"] = "kazuma"
        if s == 10 and sae_free() and not st["incited"] and r.random() < .3:  # 口で吹き込む
            st["incited"] = True
        if s == 9 and st["incited"] and not st["dissuaded"] and r.random() < .6:
            if not (place == "神社" and intent in ("dissuade","guard") and chk(r, ab["話す"])):
                st["priest_alarm"] = True
        if s == 10 and st["priest_alarm"] and "宗一郎" not in st["dead"]:   # 三日目夕 火
            if place == "診療所" and intent == "guard": pass
            elif here("久世", s) == "診療所" and r.random() < .6: st["dead"].add("久世")
        if s == 11 and st["incited"] and not st["dissuaded"]:   # 三日目夜 社
            p = .7
            if place == "神社" and intent == "guard": p = 0 if chk(r, ab["動く"]) else .35
            if r.random() < p: st["dead"].add("宗一郎")
            else: st["retry_shrine"] = True
        if s == 14 and st.get("retry_shrine") and not st["dissuaded"] and "宗一郎" not in st["dead"]:
            p = .5
            if place == "浜" and intent in ("guard","escort") and chk(r, ab["観る"]): p = .1
            if r.random() < p: st["dead"].add("宗一郎")
        # 凪
        nagi_slot = 14 if st["alert"] and r.random() < .5 else 15
        if s == nagi_slot and sae_free() and st["proof"] and "凪" not in st["dead"]:
            alone = st["chizuru_hurt"] or r.random() < .5
            if place == here("凪", s) and intent == "escort":
                # 凪は「父のことを知る人」に会いに、こっそり抜ける。信頼2なら打ち明ける
                if st["trust"]["凪"] >= 2 or chk(r, ab["観る"], -3): alone = False
            if alone and r.random() < .9: st["dead"].add("凪")
        # 警戒した紗英が瀬島を狙う（夜、人けのない所）
        if s % 4 == 3 and st["alert"] and sae_free() and place in ("灯台","分校跡","浜","港") and r.random() < .25:
            st["seijima_dead"] = True
        if intent in ("guard","escort") and place == sae_here and sae_free() and r.random() < .35:
            st["alert"] = True
        tragedy = "凪" in st["dead"] or len(st["dead"]) >= 2 or st["seijima_dead"]
        if tragedy: return True, st
    return False, st

AB = {"観る":2,"話す":2,"忍ぶ":1,"動く":1}

PLANS = {
 "何も知らない（毎コマ乱数）": {},
 # 一周目の記憶だけ：凪の夜と社の夜を張る
 "凪と社だけ張る": {11:("神社","guard"), 15:("浜","escort"), 14:("浜","escort")},
 # 防ぐ筋：事件を一つずつ潰す
 "全部を防ぐ（知り尽くし）": {0:("港","talk"),1:("診療所","talk"),2:("汐見荘","guard"),3:("汐見荘","talk"),
     4:("診療所","warn_kuze"),5:("診療所","guard"),6:("港","talk"),7:("汐見荘","guard"),
     8:("港","talk"),9:("神社","guard"),10:("診療所","guard"),11:("神社","guard"),
     12:("汐見荘","guard"),13:("神社","talk"),14:("浜","escort"),15:("浜","escort")},
 # 暴く筋：荷物と手紙で二つの証を集め、人前で問う
 "暴く（知り尽くし）": {0:("港","talk"),1:("汐見荘","search_sae"),2:("汐見荘","guard"),3:("汐見荘","talk"),
     4:("港","talk"),5:("港","letter"),6:("港","talk"),7:("汐見荘","expose"),
     8:("港","talk"),9:("神社","guard"),10:("診療所","guard"),11:("神社","guard"),
     12:("汐見荘","expose"),13:("神社","talk"),14:("浜","escort"),15:("浜","escort")},
}

N = 20000
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
r = random.Random(seed)
for name, plan in PLANS.items():
    t = 0; exp = 0
    for _ in range(N):
        tr, st = run(plan, r, AB)
        t += tr; exp += st["exposed"]
    print(f"{name}: 惨事 {t/N:.3f}  生還 {1-t/N:.3f}  暴いた {exp/N:.3f}")
