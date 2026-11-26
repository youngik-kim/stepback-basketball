# -*- coding: utf-8 -*-
"""로컬 검증: 390x844 / 1280x800 — 잠금 화면, 오답 거부, 정답 입장, 새로고침 유지, 주차 전환, 검색, 개인 카드, JS 에러, 가로 스크롤."""
import io, os, re, sys, json, threading, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUT = os.environ.get("VERIFY_OUT") or os.path.join(SITE, "_verify")
os.makedirs(OUT, exist_ok=True)
CODE = (os.environ.get('STEPBACK_ENTRY_CODE') or io.open(os.path.join(SITE, '.entry-code'), encoding='utf-8').read()).strip()
DATA = json.loads(io.open(os.path.join(SITE, 'src', 'data.json'), encoding='utf-8').read())
NAMES = {p['name'] for p in DATA['members'] + DATA['outsiders'] + DATA['guests'] + DATA['roster']} | set(DATA['absent'])
TOP = DATA['members'][0]
REB_LEAD = max(DATA['stats']['career']['rows'], key=lambda r: r['reb'])

# ---- 개인 스탯 표 기대값 (basketball/2026-11-22-스텝백-개인스탯.md 원본 기준)
STAT_HEADS = ['선수', '득점', '리바', 'ORB', 'DRB', '어시', '스틸', '블락', '턴오버', '파울', '2점', '3점', '자유투', 'MVP', '출전']
STAT_KEYS = ['pts', 'reb', 'orb', 'drb', 'ast', 'stl', 'blk', 'to', 'pf', 'fg2', 'fg3', 'ft', 'mvp', 'gp']
CELL_PLAYER = {'name': '박덕원'}
CELL_EXPECT = ['23', '3', '0', '3', '2', '7', '1', '2', '1', '73% 8/11', '11% 1/9', '100% 2/2', '5.10', '5']
SHOT_KEYS = {'fg2', 'fg3', 'ft'}

def sort_top(rows, key):
    """template.html 의 정렬 규칙과 동일: 샷은 성공률→성공개수→시도, 나머지는 값 내림, 동률은 이름."""
    def k(r):
        if key in SHOT_KEYS:
            s = r.get(key)
            return (-(s['p'] if s and s['a'] else -1), -(s['m'] if s else 0), -(s['a'] if s else 0), r['name'])
        v = r.get(key)
        return (-(-1 if v is None else v), r['name'])
    return sorted(rows, key=k)[0]['name']

SORT_TOP = {mode: {k: sort_top(v['rows'], k) for k in STAT_KEYS} for mode, v in DATA['stats'].items()}
CARD_P = sorted(DATA['stats']['event']['rows'], key=lambda r: (-r['pts'], r['name']))[0]
CARD_C = [r for r in DATA['stats']['career']['rows'] if r['name'] == CARD_P['name']]
CARD_EXPECT = [f"{CARD_P['fg2']['m']:.0f}/{CARD_P['fg2']['a']:.0f}", f"{CARD_P['fg2']['p']:.0f}%"]
if CARD_C:
    c = CARD_C[0]
    CARD_EXPECT += [f"{c['fg2']['m']:.0f}/{c['fg2']['a']:.0f}", f"{c['fg2']['p']:.0f}%"]

URL = os.environ.get("SITE_URL")
httpd = None
if not URL:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=SITE)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{httpd.server_address[1]}/"
print("target", URL)

results = []
def ok(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + ((" — " + extra) if extra else ""))

def collect(page, sink):
    page.on("console", lambda m: sink.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    page.on("pageerror", lambda e: sink.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: sink.append(f"requestfailed: {r.url} {r.failure}"))

with sync_playwright() as p:
    browser = p.chromium.launch()
    for tag, w, h in [("m", 390, 844), ("d", 1280, 800)]:
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if tag == "m" else 1)
        page = ctx.new_page()
        errs = []
        collect(page, errs)
        page.goto(URL, wait_until="load")
        page.wait_for_timeout(400)

        # 1) 잠금 화면
        ok(f"{tag}: 잠금 화면 노출", page.locator("#lock").is_visible() and not page.locator(".hero").is_visible())
        page.screenshot(path=f"{OUT}/{tag}_1_lock.png", full_page=False)

        # HTML 소스에 평문 이름이 없는지
        src = page.content()
        ok(f"{tag}: DOM 소스에 평문 이름 없음(ENC만)", not any(n in src for n in NAMES))

        # 2) 오답 거부
        page.fill("#code", "1111")
        page.click("#go")
        page.wait_for_timeout(900)
        err = page.inner_text("#lerr")
        ok(f"{tag}: 오답 거부", ("올바르지" in err) and page.locator("#lock").is_visible(), err)
        page.screenshot(path=f"{OUT}/{tag}_2_wrong.png")

        # 3) 정답 입장 (Enter 사용)
        page.fill("#code", CODE)
        page.press("#code", "Enter")
        page.wait_for_selector(".hero h1", state="visible", timeout=8000)
        page.wait_for_timeout(500)
        ok(f"{tag}: {CODE} 입장 성공", page.locator("#lock").is_hidden() and page.locator("#memberRows .rrow").count() == 16,
           f"정규 행 {page.locator('#memberRows .rrow').count()}")
        ok(f"{tag}: 승률 1위 {TOP['name']} {TOP['rate']}%", page.locator("#memberRows .rrow").first.inner_text().find(str(TOP['rate'])) >= 0,
           page.locator("#memberRows .rrow").first.inner_text().replace("\n", " | ")[:70])
        page.screenshot(path=f"{OUT}/{tag}_3_home.png")

        # 4) 가로 스크롤 없음
        sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        ok(f"{tag}: 가로 스크롤 없음", sw <= iw + 1, f"scrollWidth={sw} innerWidth={iw}")

        # 5) 재접속 유지 (새로고침)
        page.reload(wait_until="load")
        page.wait_for_timeout(700)
        ok(f"{tag}: 새로고침 자동 입장", page.locator("#lock").is_hidden() and page.locator("#memberRows .rrow").count() == 16)

        # 6) 주차 전환: 첫 회차
        opts = page.evaluate("Array.from(document.querySelectorAll('#weekSel option')).map(o=>o.value)")
        ok(f"{tag}: 주차 45개", len(opts) == 45, f"opts={len(opts)} first={opts[0]} last={opts[-1]}")
        page.select_option("#weekSel", opts[0])
        page.wait_for_timeout(500)
        res = page.inner_text("#resWeek")
        ok(f"{tag}: 첫 회차 전환", opts[0] in res and "1회차" in res, res)
        ok(f"{tag}: 과거 배너 표시", page.locator("#pastBanner").is_visible() and "2026-01-03" in page.inner_text("#pastBanner"))
        ok(f"{tag}: 과거 시점 순위권 6명(1회차)", page.locator("#memberRows .rrow").count() == 6,
           f"rows={page.locator('#memberRows .rrow').count()}")
        page.screenshot(path=f"{OUT}/{tag}_4_past.png")

        # 최신 버튼
        page.click("#latestBtn")
        page.wait_for_timeout(500)
        ok(f"{tag}: 최신 복귀", page.locator("#latestBtn").is_hidden() and page.locator("#memberRows .rrow").count() == 16)

        # 7) 다음/이전 버튼
        page.click("#prevBtn")
        page.wait_for_timeout(300)
        ok(f"{tag}: ‹ 이전 회차", "44회차" in page.inner_text("#resWeek"), page.inner_text("#resWeek"))
        page.click("#latestBtn"); page.wait_for_timeout(300)

        # 8) 검색
        page.fill("#q", "김")
        page.wait_for_timeout(300)
        n_reg = page.locator("#memberRows .rrow").count()
        n_out = page.locator("#outRows .otile").count()
        hint = page.inner_text("#searchHint")
        ok(f"{tag}: 검색 필터", n_reg == 5 and n_out == 1 and "검색 결과" in hint, f"정규 {n_reg} / 순위외 {n_out} / {hint}")
        page.locator("#clr").click(); page.wait_for_timeout(250)

        # 9) 개인 카드
        page.locator("#memberRows .rrow").first.click()
        page.wait_for_selector("#modal:not([hidden])", timeout=4000)
        body = page.inner_text("#mBody")
        ok(f"{tag}: 개인 카드 열림", "승률" in body and "회차별 기록" in body, body.split("\n")[0])
        ok(f"{tag}: 카드에 스탯·신장·포지션", ("득점" in body) and ("cm" in body) and ("PG" in body or "SF" in body or "PF" in body or "SG" in body))
        page.screenshot(path=f"{OUT}/{tag}_5_modal.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        ok(f"{tag}: 카드 닫기", page.locator("#modal").is_hidden())

        # 10) 개인 스탯: 전 항목 열 · 헤더/칩 정렬 · 선수 열 고정 · 좌우 스크롤
        page.locator("#secStats").scroll_into_view_if_needed(); page.wait_for_timeout(250)
        heads = page.eval_on_selector_all("#statHead th", r"els=>els.map(e=>e.innerText.replace(/[\s\u25bc]/g,''))")
        ok(f"{tag}: 스탯 헤더 15열", heads == STAT_HEADS, " / ".join(heads))
        ok(f"{tag}: 경기 15행 · 행당 15칸", page.locator("#statRows .strow").count() == 15
           and page.locator("#statRows .strow").first.locator("td").count() == 14,
           f"rows={page.locator('#statRows .strow').count()} tds={page.locator('#statRows .strow').first.locator('td').count()}")
        ok(f"{tag}: 정렬 칩 {len(STAT_KEYS) - len(SHOT_KEYS)}개", page.locator("#sortRow .sortchip").count() == len(STAT_KEYS) - len(SHOT_KEYS), f"{page.locator('#sortRow .sortchip').count()}")

        # 기록지 값 그대로 들어갔는지 (박덕원: 2점 8/11·73% … ORB 0 · DRB 3 · 스틸 7 · 턴오버 2)
        cells = page.eval_on_selector(f"#statRows .strow[data-person='{CELL_PLAYER['name']}']",
                                      "tr=>Array.from(tr.children).slice(1).map(td=>td.innerText.replace(/\\s+/g,' ').trim())")
        ok(f"{tag}: {CELL_PLAYER['name']} 전 항목 셀 값", cells == CELL_EXPECT, " | ".join(cells))

        # 가로 스크롤: 컨테이너 내부만, 문서 전체는 그대로
        sc = page.eval_on_selector("#statScroll", "el=>({sw:el.scrollWidth,cw:el.clientWidth,sl:el.scrollLeft})")
        sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        ok(f"{tag}: 문서 전체 가로 스크롤 없음", sw <= iw + 1, f"scrollWidth={sw} innerWidth={iw}")
        if w < 760:
            ok(f"{tag}: 390px에서 표가 가로로 넘침(내부 스크롤)", sc["sw"] > sc["cw"] + 60, f"scrollWidth={sc['sw']} clientWidth={sc['cw']}")
            x0 = page.eval_on_selector("#statHead th.pcol", "el=>el.getBoundingClientRect().left")
            page.eval_on_selector("#statScroll", "el=>{el.scrollLeft=250}"); page.wait_for_timeout(200)
            x1 = page.eval_on_selector("#statHead th.pcol", "el=>el.getBoundingClientRect().left")
            sx1 = page.eval_on_selector("#statScroll", "el=>el.scrollLeft")
            ok(f"{tag}: 선수 열 왼쪽 고정(sticky)", abs(x0 - x1) <= 1 and sx1 > 200, f"x {x0:.1f}→{x1:.1f} scrollLeft={sx1}")
            page.eval_on_selector("#statScroll", "el=>{el.scrollLeft=el.scrollWidth}"); page.wait_for_timeout(250)
            last = page.eval_on_selector("#statHead th:last-child", "el=>el.getBoundingClientRect()")
            ok(f"{tag}: 끝까지 밀면 마지막 열(출전) 보임", 0 <= last["left"] and last["right"] <= iw + 1, f"left={last['left']:.0f} right={last['right']:.0f}")
            ok(f"{tag}: 끝에서 오른쪽 페이드 사라짐", page.eval_on_selector("#statFade", "el=>el.classList.contains('off')"))
            sw2 = page.evaluate("document.documentElement.scrollWidth")
            ok(f"{tag}: 스크롤 후에도 문서 가로 흔들림 없음", sw2 <= iw + 1, f"scrollWidth={sw2}")
            page.screenshot(path=f"{OUT}/{tag}_6_stats.png")
            page.eval_on_selector("#statScroll", "el=>{el.scrollLeft=0}"); page.wait_for_timeout(150)
            ok(f"{tag}: 왼쪽 복귀 시 페이드 다시 표시", not page.eval_on_selector("#statFade", "el=>el.classList.contains('off')"))
        page.screenshot(path=f"{OUT}/{tag}_6b_stats_left.png")

        # 헤더 클릭 정렬 — 14개 열 전부, 최상단이 데이터 기대값과 일치
        for key in STAT_KEYS:
            page.click(f"#statHead [data-sort='{key}']"); page.wait_for_timeout(120)
            top = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
            exp = SORT_TOP['event'][key]
            ok(f"{tag}: 헤더 정렬 {key} → {exp}", top == exp, f"got {top}")
            if key == 'stl':
                page.screenshot(path=f"{OUT}/{tag}_6c_stats_sort_stl.png")

        # 누적 탭 + 칩 정렬
        page.click("#tabCareer"); page.wait_for_timeout(250)
        ok(f"{tag}: 누적 스탯 16명", page.locator("#statRows .strow").count() == 16, f"{page.locator('#statRows .strow').count()}")
        page.click("#sortRow [data-sort='reb']"); page.wait_for_timeout(250)
        first = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
        ok(f"{tag}: 리바운드 정렬", first == REB_LEAD['name'], first)
        page.click("#sortRow [data-sort='to']"); page.wait_for_timeout(200)
        first = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
        ok(f"{tag}: 턴오버 정렬", first == SORT_TOP['career']['to'], first)
        page.screenshot(path=f"{OUT}/{tag}_6d_stats_career.png")
        page.click("#tabEvent"); page.click("#sortRow [data-sort='pts']"); page.wait_for_timeout(200)

        # 개인 카드(모달) — 두 시점 전 항목
        page.locator("#statRows .strow").first.click()
        page.wait_for_selector("#modal:not([hidden])", timeout=4000)
        mb = page.inner_text("#mBody")
        need = ["2점", "3점", "자유투", "득점", "리바운드", "ORB", "DRB", "어시스트", "스틸", "블락", "턴오버", "파울", "MVP", "출전"]
        ok(f"{tag}: 개인 카드 전 항목 표시", all(k in mb for k in need), "".join(k for k in need if k not in mb) or "all")
        ok(f"{tag}: 개인 카드 2점 성공/시도+% (경기·누적)", all(x in mb for x in CARD_EXPECT), f"{CARD_EXPECT} · " + mb.replace("\n", " ")[:60])
        page.screenshot(path=f"{OUT}/{tag}_6e_stats_modal.png")
        page.keyboard.press("Escape"); page.wait_for_timeout(250)

        # 11) 로스터
        page.locator("#secRoster").scroll_into_view_if_needed()
        ok(f"{tag}: 로스터 21명", page.locator("#rosterGrid .rcell").count() == 21, f"{page.locator('#rosterGrid .rcell').count()}")
        page.click('[data-pos="PG"]'); page.wait_for_timeout(250)
        ok(f"{tag}: PG 필터 4명", page.locator("#rosterGrid .rcell").count() == 4, f"{page.locator('#rosterGrid .rcell').count()}")
        page.screenshot(path=f"{OUT}/{tag}_7_roster.png")
        page.click('[data-pos="ALL"]')

        # 12) 주간 아코디언 45개 + 펼치기
        ok(f"{tag}: 주간 카드 45개", page.locator("#weekList .wkcard").count() == 45)
        page.locator('#weekList .wkcard').nth(1).locator("summary").click()
        page.wait_for_timeout(250)
        ok(f"{tag}: 주간 펼침", page.locator('#weekList .wkcard').nth(1).get_attribute("open") is not None)

        # 13) 잠금 버튼
        page.locator("#lockBtn").scroll_into_view_if_needed()
        page.click("#lockBtn")
        page.wait_for_timeout(900)
        ok(f"{tag}: 잠금 버튼 → 잠금 화면", page.locator("#lock").is_visible(), "")
        page.screenshot(path=f"{OUT}/{tag}_8_relocked.png")

        # 14) 콘솔 에러
        ok(f"{tag}: JS 에러 0건", len(errs) == 0, "; ".join(errs[:4]))
        ctx.close()

    # 데스크톱 전체 페이지(잠금 해제 상태) 캡처
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(URL, wait_until="load")
    page.fill("#code", CODE); page.press("#code", "Enter")
    page.wait_for_selector("#memberRows .rrow", timeout=8000)
    page.wait_for_timeout(600)
    page.screenshot(path=f"{OUT}/d_9_full.png", full_page=True)
    ctx.close()
    browser.close()
if httpd: httpd.shutdown()

fails = [r for r in results if not r[1]]
print("\n=== 결과: %d/%d 통과, 실패 %d ===" % (len(results) - len(fails), len(results), len(fails)))
for f in fails:
    print("  FAIL:", f[0], f[2])
sys.exit(1 if fails else 0)
