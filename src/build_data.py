# -*- coding: utf-8 -*-
"""스텝백 웹페이지용 DATA 생성 + 누적 기록 검증.

원본:
  basketball/stepback-records.md
  basketball/stepback-guests.md
  basketball/2026-11-22-스텝백-개인스탯.md
출력:
  stepback-basketball-site/src/data.json   (평문 — 배포 금지, .gitignore 대상)
"""
import io, json, os, re, sys, math

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(SITE)

def read(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()

rec = read("basketball/stepback-records.md")
gst = read("basketball/stepback-guests.md")
stat = read("basketball/2026-11-22-스텝백-개인스탯.md")
hist = read("basketball/2026-10-25~11-15-스텝백-개인스탯.md")
PREVIEW_PATH = "basketball/stepback-match-preview.md"
prev_txt = read(PREVIEW_PATH) if os.path.exists(os.path.join(ROOT, PREVIEW_PATH)) else ""

def clean(s):
    return s.replace("**", "").replace("`", "").strip()

def rows(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", line):
            out.append([c.strip() for c in line.strip("|").split("|")])
    return out

def wdl(s):
    """'59승 4무 31패' / '5승 2패' -> (w, d, l)"""
    s = clean(s)
    w = re.search(r"(\d+)승", s)
    d = re.search(r"(\d+)무", s)
    l = re.search(r"(\d+)패", s)
    return (int(w.group(1)) if w else 0,
            int(d.group(1)) if d else 0,
            int(l.group(1)) if l else 0)

def name_of(cell):
    c = clean(cell)
    # 이름 옆 '(구분)' 표기는 로스터 role 에서 관리하므로 이름에서 걷어낸다
    c = re.sub(r"\*?\(\s*(?:준회원|게스트)\s*\)\*?", " ", c)
    c = re.sub(r"\s{2,}", " ", c).strip()
    perfect = "[개근]" in c
    c = c.replace("[개근]", "").strip()
    return c, perfect

# ---------------------------------------------------------------- 정규 / 순위 외
reg_block = rec.split("## 🏆 정규 순위")[1].split("## ⏳ 순위 외")[0]
out_block = rec.split("## ⏳ 순위 외")[1].split("## 🎖️ 시즌 하이라이트")[0]

members = []
for r in rows(reg_block)[1:]:
    name, perfect = name_of(r[1])
    weeks = int(re.search(r"(\d+)회", r[2]).group(1))
    att = float(re.search(r"\(([\d.]+)%\)", r[2]).group(1))
    games = int(re.search(r"(\d+)경기", r[3]).group(1))
    w, d, l = wdl(r[4])
    rate = float(clean(r[5]).replace("%", ""))
    tw, td, tl = wdl(r[6])
    hw, hd, hl = wdl(r[7])
    members.append(dict(rank=int(clean(r[0])), name=name, weeks=weeks, att=att,
                        games=games, w=w, d=d, l=l, rate=rate,
                        two=dict(w=tw, d=td, l=tl), three=dict(w=hw, d=hd, l=hl),
                        perfect=perfect))

outsiders = []
for r in rows(out_block)[1:]:
    name, perfect = name_of(r[1])
    weeks = int(re.search(r"(\d+)회", r[2]).group(1))
    att = float(re.search(r"\(([\d.]+)%\)", r[2]).group(1))
    games = int(re.search(r"(\d+)경기", r[3]).group(1))
    w, d, l = wdl(r[4])
    rate = float(clean(r[5]).replace("%", ""))
    note = clean(r[6])
    outsiders.append(dict(rank=clean(r[0]), name=name, weeks=weeks, att=att,
                          games=games, w=w, d=d, l=l, rate=rate, note=note,
                          perfect=perfect))

absent = []        # 미출전 정회원
absent_guests = [] # 미출전 게스트 (로스터에만 등록)
for pat, bucket in ((r"미출전 정회원 \((\d+)명\): ([^\n]+)", absent),):
    m = re.search(pat, rec)
    if m:
        names = m.group(2).split("—")[0]
        bucket.extend([a.strip() for a in names.split(",") if a.strip()])
m = re.search(r"미출전 게스트 \((\d+)명\): ([^\n]+)", gst)
if m:
    names = m.group(2).split("—")[0]
    absent_guests.extend([a.strip() for a in names.split(",") if a.strip()])

# ---------------------------------------------------------------- 게스트
guests = []
for r in rows(gst.split("## 📊 게스트 누적 전적")[1])[1:]:
    name, _ = name_of(r[1])
    weeks = int(re.search(r"(\d+)회?", r[2]).group(1))
    w, d, l = wdl(r[3])
    rate = float(clean(r[4]).replace("%", ""))
    dates = [x.strip() for x in r[5].split(",")]
    guests.append(dict(rank=int(clean(r[0])), name=name, weeks=weeks, w=w, d=d, l=l,
                       rate=rate, dates=dates, absent=False))

# 출전 기록이 없는 게스트(로스터에만 등록) — 순위 맨 뒤, 출전 0회로 표기
guest_rows_played = len(guests)
for nm in absent_guests:
    guests.append(dict(rank=guest_rows_played + 1 + absent_guests.index(nm), name=nm, weeks=0,
                       w=0, d=0, l=0, rate=None, dates=[], absent=True))

# ---------------------------------------------------------------- 주간 로그
log = rec.split("## 📅 주간 경기 로그")[1]
blocks = re.split(r"^### ", log, flags=re.M)[1:]

TEAM_RE = re.compile(r"([가-힣]{2,4})\s+(\d+)승(\d+)무(\d+)패")
GAME_RE = re.compile(r"^\s*-\s*([가-힣A-Za-z0-9]+)\s+(\d+)\s*:\s*(\d+)\s+([가-힣A-Za-z0-9]+)")

weeks = []
for b in blocks:
    lines = b.split("\n")
    head = lines[0].strip()
    dm = re.match(r"(\d{4}-\d{2}-\d{2})\s*·\s*(.+)$", head)
    date, wtype = dm.group(1), dm.group(2).strip()

    body = "\n".join(lines[1:])
    memos = []
    stat_line = None
    score_lines, roster_line = [], None
    mode = None
    for ln in lines[1:]:
        if "**팀 성적**" in ln:
            stat_line = ln.split("**팀 성적**:")[1].strip(); mode = None
        elif "**메모**" in ln:
            memos.append(ln.split("**메모**:")[1].strip()); mode = None
        elif "**스코어**" in ln:
            mode = "score"
        elif "**명단**" in ln:
            mode = "roster"; roster_line = ln.split("**명단**:")[1].strip()
        elif mode == "score" and re.match(r"^\s*-\s*", ln):
            score_lines.append(ln.strip())

    standings = []
    if stat_line:
        for i, mm in enumerate(TEAM_RE.finditer(stat_line)):
            standings.append(dict(team=mm.group(1), w=int(mm.group(2)),
                                  d=int(mm.group(3)), l=int(mm.group(4)), diff=0, pos=i + 1))
    by_team = {s["team"]: s for s in standings}

    games = []
    for ln in score_lines:
        gm = GAME_RE.match(ln)
        if not gm:
            continue
        a, as_, bs, bb = gm.group(1), int(gm.group(2)), int(gm.group(3)), gm.group(4)
        if "무승부" in ln:
            win = "무"
        else:
            wm = re.search(r"\*\*([^*]+?)\s*승\*\*", ln)
            win = wm.group(1).strip() if wm else ("A" if as_ > bs else "B" if bs > as_ else "무")
        games.append(dict(a=a, as_=as_, b=bb, bs=bs, win=win))
        if a in by_team:
            by_team[a]["diff"] += as_ - bs
        if bb in by_team:
            by_team[bb]["diff"] += bs - as_

    rosters = {}
    if roster_line:
        for team, names in re.findall(r"([가-힣]{2,4})\(([^)]*)\)", roster_line):
            cells = [n.strip() for n in names.split(",") if n.strip()]
            if len(cells) == 1 and ("미기재" in cells[0] or cells[0] == ""):
                cells = []
            rosters[team] = cells

    order = {s["team"]: i for i, s in enumerate(standings)}
    # 미출전(백업 등)은 항상 뒤로, 출전 팀만 순위를 매긴다
    standings.sort(key=lambda s: (0 if (s["w"] + s["d"] + s["l"]) > 0 else 1,
                                  -s["w"], -s["d"], -s["diff"], order[s["team"]]))
    pos = 0
    for s in standings:
        if (s["w"] + s["d"] + s["l"]) > 0:
            pos += 1
            s["pos"] = pos
        else:
            s["pos"] = None

    sheet = dict(standings=standings, games=games, rosters=rosters,
                 labeled=bool(rosters), note=memos[-1] if memos else "")
    weeks.append(dict(date=date, type=wtype, sheets=[sheet],
                      note=memos[0] if memos else ""))

# 같은 날짜(2/15) 두 장은 한 회차로 합친다 — 개인 집계는 장별 팀 성적을 따로 적용
merged = []
for wk in weeks:
    if merged and merged[-1]["date"] == wk["date"]:
        merged[-1]["sheets"].extend(wk["sheets"])
        merged[-1]["note"] = (merged[-1]["note"] + " / " + wk["note"]).strip(" /")
    else:
        merged.append(wk)
weeks = merged

def label(d):
    return d[5:7] + "/" + d[8:10]

# ---------------------------------------------------------------- 검증: 로스터 재계산
calc = {}
for wk in weeks:
    for sheet in wk["sheets"]:
        by_team = {s["team"]: s for s in sheet["standings"]}
        for team, names in sheet["rosters"].items():
            st = by_team.get(team, dict(w=0, d=0, l=0))
            for nm in names:
                c = calc.setdefault(nm, dict(w=0, d=0, l=0, weeks=set(),
                                             two=dict(w=0, d=0, l=0), three=dict(w=0, d=0, l=0)))
                c["w"] += st["w"]; c["d"] += st["d"]; c["l"] += st["l"]
                c["weeks"].add(wk["date"])
                key = "two" if wk["type"].startswith("2") else "three"
                c[key]["w"] += st["w"]; c[key]["d"] += st["d"]; c[key]["l"] += st["l"]

errors = []
def check(p, kind):
    c = calc.get(p["name"])
    if not c:
        errors.append(f"{kind} 미출전? {p['name']}")
        return
    got = (c["w"], c["d"], c["l"])
    exp = (p["w"], p["d"], p["l"])
    if got != exp:
        errors.append(f"{kind} {p['name']}: 표 {exp} vs 계산 {got}")
    if len(c["weeks"]) != p["weeks"]:
        errors.append(f"{kind} {p['name']}: 출전 {p['weeks']} vs 계산 {len(c['weeks'])}")
    if kind == "정규" and ("two" in p):
        if (c["two"]["w"], c["two"]["d"], c["two"]["l"]) != (p["two"]["w"], p["two"]["d"], p["two"]["l"]):
            errors.append(f"{kind} {p['name']}: 2파전 표 {p['two']} vs 계산 {c['two']}")
        if (c["three"]["w"], c["three"]["d"], c["three"]["l"]) != (p["three"]["w"], p["three"]["d"], p["three"]["l"]):
            errors.append(f"{kind} {p['name']}: 3파전 표 {p['three']} vs 계산 {c['three']}")

for p in members:
    check(p, "정규")
for p in outsiders:
    check(p, "순위외")
for g in guests:
    if not g["absent"]:
        check(g, "게스트")

unknown = sorted(set(calc) - set(m["name"] for m in members) - set(o["name"] for o in outsiders)
                 - set(g["name"] for g in guests))
if unknown:
    errors.append("명단에만 있는 이름: " + ", ".join(unknown))

# 순위 검증
order = sorted(members, key=lambda p: (-p["rate"], -p["w"], -p["games"], p["name"]))
if [p["rank"] for p in order] != list(range(1, len(members) + 1)):
    errors.append("정규 순위 불일치: " + ", ".join(f"{p['rank']}:{p['name']}" for p in order))

two_n = sum(1 for w in weeks if w["type"].startswith("2"))
three_n = sum(1 for w in weeks if w["type"].startswith("3"))
games_n = sum(len(s["games"]) for w in weeks for s in w["sheets"])

print(f"주차 {len(weeks)} (2파전 {two_n} / 3파전 {three_n}) · 경기 {games_n} · 기록지 {sum(len(w['sheets']) for w in weeks)}장")
print(f"정규 {len(members)} · 순위외 {len(outsiders)} · 게스트 {len(guests)}(미출전 {len(absent_guests)}) · 미출전 정회원 {absent}")
print("검증 오류:", errors if errors else "없음")

# ---------------------------------------------------------------- 11/22 스탯 · 누적
def parse_shot(cell):
    c = clean(cell)
    if c in ("-", "", "—"):
        return None
    m = re.match(r"([\d.]+)\s*/\s*([\d.]+)\s*\(([\d.]+)%\)", c)
    if not m:
        return None
    return dict(m=float(m.group(1)), a=float(m.group(2)), p=float(m.group(3)))

def num(cell):
    c = clean(cell)
    if c in ("-", "", "—"):
        return None
    try:
        return float(c)
    except ValueError:
        return None

def parse_stats(block):
    out = []
    for r in rows(block)[1:]:
        if len(r) < 14:
            continue
        rec_p = dict(
            name=clean(r[0]),
            fg2=parse_shot(r[1]), fg3=parse_shot(r[2]), ft=parse_shot(r[3]),
            pts=num(r[4]), orb=num(r[5]), drb=num(r[6]), ast=num(r[7]),
            stl=num(r[8]), blk=num(r[9]), to=num(r[10]), pf=num(r[11]),
            mvp=num(r[12]), gp=num(r[13]),
        )
        rec_p["reb"] = (rec_p["orb"] or 0) + (rec_p["drb"] or 0)
        # 쿼터당 평균득점 = 총득점 ÷ 출전수 (출전 0이면 없음)
        rec_p["ppg"] = round(rec_p["pts"] / rec_p["gp"], 1) if (rec_p["pts"] is not None and rec_p["gp"]) else None
        out.append(rec_p)
    return out

overall = parse_stats(stat.split("## 스텝백 누적기록")[0])
career = parse_stats(stat.split("## 스텝백 누적기록")[1].split("## 스텝백 정회원 신장")[0])

# --- 경기 날짜별 전체기록(11/22 최신 + 10/25~11/15 5주치) — 최신순
events = [dict(date="2026-11-22", rows=overall, tag="")]
for sec in re.split(r"^## ", hist, flags=re.M)[1:]:
    head, _, body = sec.partition("\n")
    if "누적" in head:          # 11/8 기준 누적 스냅샷은 참고용 — 드롭다운에 넣지 않는다
        continue
    dm = re.search(r"(\d{4}-\d{2}-\d{2})", head)
    if not dm:
        continue
    events.append(dict(date=dm.group(1), rows=parse_stats(body),
                       tag="3G" if "3G" in head else ""))
events.sort(key=lambda e: e["date"], reverse=True)
roster_block = stat.split("## 스텝백 로스터(정회원·게스트) 신장")[1]

roster = []
for r in rows(roster_block)[1:]:
    if len(r) < 4:
        continue
    nm = clean(r[0])
    no = clean(r[1]); h = clean(r[2]); pos = clean(r[3])
    role = "게스트" if len(r) > 4 and "게스트" in clean(r[4]) else "정회원"
    roster.append(dict(name=nm, no=(None if no in ("-", "") else no),
                       height=(None if h in ("-", "") else int(h)), pos=pos,
                       posMain=pos.split("/")[0], role=role))

# 로스터의 구분(정회원/게스트)을 순위 표에도 붙인다
ROLE = {r["name"]: r["role"] for r in roster}
for p in members + outsiders:
    p["role"] = ROLE.get(p["name"], "정회원")

guest_names = [r["name"] for r in roster if r["role"] == "게스트"]
reg_names = [r["name"] for r in roster if r["role"] == "정회원"]
if len(roster) != 21 or len(reg_names) != 17 or len(guest_names) != 4:
    errors.append(f"로스터 구분 인원 이상: 전체 {len(roster)} · 정회원 {len(reg_names)} · 게스트 {len(guest_names)} ({', '.join(guest_names)})")
# 게스트 표(출전 + 미출전)와 로스터 게스트가 일치하는지
if len(guests) != 75 or len([g for g in guests if not g["absent"]]) != 74:
    errors.append(f"게스트 인원 이상: 표 {len(guests)}명(미출전 {len(absent_guests)}) — 74 출전 + 1 미출전 기대")
missing_guest = [n for n in guest_names if n not in {g["name"] for g in guests}]
if missing_guest:
    errors.append("로스터 게스트가 게스트 표에 없음: " + ", ".join(missing_guest))
if len(members) != 15 or len(outsiders) != 2:
    errors.append(f"정규 순위 인원 이상: 정규 {len(members)} · 순위 외 {len(outsiders)} (15 · 2 기대)")

# --- 스탯 열 완비 검사 (2점·3점·자유투·ORB·DRB·리바총합·어시·스틸·블락·턴오버·파울·MVP·출전)
STAT_KEYS = ["pts", "ppg", "fg2", "fg3", "ft", "orb", "drb", "reb", "ast", "stl", "blk", "to", "pf", "mvp", "gp"]
for label, srows, exp in (("11/22", overall, 15), ("누적", career, 16)):
    missing = [(r["name"], k) for r in srows for k in STAT_KEYS if k not in r]
    if missing:
        errors.append(f"스탯 {label} 열 누락: {missing}")
    if len(srows) != exp:
        errors.append(f"스탯 {label} 인원 {len(srows)}명 (기록지 {exp}명)")
    for r in srows:
        if (r["orb"] or 0) + (r["drb"] or 0) != r["reb"]:
            errors.append(f"스탯 {label} {r['name']}: 리바총합 {r['reb']} != ORB+DRB")
        if r["gp"] and r["pts"] is not None:
            if r["ppg"] != round(r["pts"] / r["gp"], 1):
                errors.append(f"스탯 {label} {r['name']}: 평균 {r['ppg']} != {r['pts']}/{r['gp']}")
    if any(r["name"] != clean(r["name"]) for r in srows):
        errors.append(f"스탯 {label} 이름 정리 오류")

print(f"스탯: 11/22 {len(overall)}명 · 누적 {len(career)}명 · 로스터 {len(roster)}명 · 열 {len(STAT_KEYS)}종(리바총합 포함) 확인")
print(f"로스터 구분: 정회원 {len(reg_names)}명 · 게스트 {len(guest_names)}명 ({', '.join(guest_names)})")

# --- 경기 날짜별 기록(11/22·11/15·11/08·11/01·10/25) 검산
EXPECT_EVENTS = [("2026-11-22", 15, True), ("2026-11-15", 12, True), ("2026-11-08", 14, True),
                 ("2026-11-01", 12, False), ("2026-10-25", 10, False)]
warn = []
if [e["date"] for e in events] != [x[0] for x in EXPECT_EVENTS]:
    errors.append("경기 날짜 목록 이상: " + ", ".join(e["date"] for e in events))
for e, (ed, en, has_mvp) in zip(events, EXPECT_EVENTS):
    rs = e["rows"]
    if len(rs) != en:
        errors.append(f"경기 {ed} 인원 {len(rs)}명 (기록지 {en}명)")
    if len({r["name"] for r in rs}) != len(rs):
        errors.append(f"경기 {ed} 이름 중복")
    for r in rs:
        if (r["orb"] or 0) + (r["drb"] or 0) != r["reb"]:
            errors.append(f"경기 {ed} {r['name']}: 리바총합 {r['reb']} != ORB+DRB")
        if r["gp"] and r["pts"] is not None and r["ppg"] != round(r["pts"] / r["gp"], 1):
            errors.append(f"경기 {ed} {r['name']}: 평균 {r['ppg']} != {r['pts']}/{r['gp']}")
        if has_mvp and r["mvp"] is None:
            errors.append(f"경기 {ed} {r['name']}: MVP 포인트 없음")
        if not has_mvp and r["mvp"] is not None:
            errors.append(f"경기 {ed} {r['name']}: MVP 포인트 {r['mvp']} (기록지에 없는 열)")
        # 총득점은 시트 원본 값 — 시트가 자유투 성공을 두 번 더하는 특성이 있어 참고 경고만 남긴다
        pm2 = r["fg2"]["m"] if r["fg2"] else 0
        pm3 = r["fg3"]["m"] if r["fg3"] else 0
        ftm = r["ft"]["m"] if r["ft"] else 0
        base = 2 * pm2 + 3 * pm3
        if r["pts"] is not None and min(abs(r["pts"] - (base + ftm)), abs(r["pts"] - (base + 2 * ftm))) > 0.01:
            warn.append(f"{ed} {r['name']}: 총득점 {r['pts']} · 샷합 {base} · 자유투 {ftm}")

print("경기별: " + " · ".join(f"{e['date'][5:]}{('(' + e['tag'] + ')') if e['tag'] else ''} {len(e['rows'])}명" for e in events))
print("총득점 검산 경고(시트 산식 차이):", warn if warn else "없음")

# ---------------------------------------------------------------- 매치 프리뷰 (경기 전 예상)
# basketball/stepback-match-preview.md — 회차(경기일)별 `### YYYY-MM-DD · 형식` 블록
#   - **작성**: YYYY-MM-DD
#   - **예상 1위**: 팀 승률%
#   - **팀별 예상**  ->  `- 팀명 승률% — 선수, 선수, …`
#   - **가상**: 안재윤 50.0%, 김준성 50.0%   (선택 · 가상 선수의 가정 승률)
#   - **메모**: 한 줄
def parse_previews(text):
    out = {}
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)   # 예시 블록은 주석이라 건너뜁니다
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)   # 코드블록 안 예시도 건너뜁니다
    for sec in re.split(r"^### ", text, flags=re.M)[1:]:
        head, _, body = sec.partition("\n")
        dm = re.match(r"(\d{4}-\d{2}-\d{2})\s*·\s*(.+?)\s*$", head.strip())
        if not dm:
            continue
        date, wtype = dm.group(1), dm.group(2)
        written, expected, note, teams = None, None, "", []
        fakes = {}
        mode = None
        for ln in body.splitlines():
            s = ln.strip()
            if not s or s.startswith(">") or s.startswith("<!--") or s.startswith("#"):
                continue
            if "**작성**" in s:
                written = clean(re.split(r"[:：]", s, 1)[1]) if re.search(r"[:：]", s) else None
                mode = None
            elif "**예상 1위**" in s:
                mv = re.search(r"([^\s:：]+)\s+([\d.]+)\s*%?", s.split("**", 2)[-1])
                if mv:
                    expected = dict(team=mv.group(1).strip(), rate=float(mv.group(2)))
                mode = None
            elif "**팀별 예상**" in s:
                mode = "teams"
            elif "**가상**" in s:
                seg = re.split(r"[:：]", s, 1)[1] if re.search(r"[:：]", s) else ""
                for tok in re.split(r"[,·]", seg):
                    mf = re.match(r"^\s*([^\s]+)\s+([\d.]+)\s*%?\s*$", tok.strip())
                    if mf:
                        fakes[mf.group(1)] = float(mf.group(2))
                mode = None
            elif "**메모**" in s:
                note = clean(re.split(r"[:：]", s, 1)[1]) if re.search(r"[:：]", s) else ""
                mode = None
            elif mode == "teams" and re.match(r"^[-*]\s+", s):
                mt = re.match(r"^[-*]\s*(.+?)\s+([\d.]+)\s*%\s*(?:[—–\-]\s*)?(.*)$", s)
                if mt:
                    players = [p.strip() for p in re.split(r"[,·]", mt.group(3)) if p.strip()]
                    teams.append(dict(team=mt.group(1).strip(), rate=float(mt.group(2)), players=players))
        teams.sort(key=lambda t: -t["rate"])
        if not teams:
            continue
        if not expected:
            expected = dict(team=teams[0]["team"], rate=teams[0]["rate"])
        out[date] = dict(date=date, type=wtype, written=written, expected=expected,
                         teams=teams, note=note, fakes=fakes)
    return out

previews = parse_previews(prev_txt)
print("매치 프리뷰:", ", ".join(f"{d}({p['type']}, {len(p['teams'])}팀)" for d, p in sorted(previews.items())) or "없음")
last_date = weeks[-1]["date"]
for d in previews:
    if d not in {w["date"] for w in weeks} and d < last_date:
        errors.append(f"프리뷰 날짜 {d} 가 회차 로그에 없습니다(오타?)")
upcoming = [previews[d] for d in sorted(previews) if d > last_date]

# ---------------------------------------------------------------- 하이라이트
best = max(members, key=lambda p: p["rate"])
most_w = max(members, key=lambda p: p["w"])
most_weeks = max(members, key=lambda p: p["weeks"])
perfect = [p["name"] for p in members if p["perfect"]]
h = dict(best=dict(name=best["name"], rate=best["rate"], w=best["w"], d=best["d"], l=best["l"]),
         mostWins=dict(name=most_w["name"], w=most_w["w"], rate=most_w["rate"]),
         mostWeeks=dict(name=most_weeks["name"], weeks=most_weeks["weeks"]),
         perfect=perfect)

data = dict(
    team="스텝백", teamEn="STEPBACK", venue="시흥 SH스포츠센터", day="일요일",
    period=dict(start=weeks[0]["date"], end=weeks[-1]["date"], weeks=len(weeks),
                sheets=sum(len(w["sheets"]) for w in weeks), games=games_n,
                two=two_n, three=three_n),
    criteria=dict(minRate=40, minWeeks=18, totalWeeks=len(weeks),
                  text="전체 45회 중 참여율 40% 이상(18회 이상) — 동률 시 다승 → 경기수 → 가나다"),
    members=members, outsiders=outsiders, absent=absent, absentGuests=absent_guests,
    guests=guests, roster=roster,
    rosterMeta=dict(total=len(roster), regular=len(reg_names), guest=len(guest_names)),
    stats=dict(event=dict(date=events[0]["date"], tag=events[0]["tag"], label="26.11.22 경기", rows=events[0]["rows"]),
               career=dict(date="2026-11-22", label="시즌 누적", rows=career),
               events=[dict(date=e["date"], tag=e["tag"],
                            label=e["date"][5:7] + "." + e["date"][8:10] + " 경기" + (" " + e["tag"] if e["tag"] else ""),
                            rows=e["rows"]) for e in events]),
    highlight=h,
    weeks=[dict(date=w["date"], type=w["type"], note=w["note"], sheets=w["sheets"],
                preview=previews.get(w["date"]))
           for w in weeks],
    upcomingPreviews=upcoming,
)

out_path = os.path.join(SITE, "src", "data.json")
json.dump(data, io.open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장:", out_path, os.path.getsize(out_path), "bytes")
if errors:
    sys.exit(1)
