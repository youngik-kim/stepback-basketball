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

        # 10) 스탯 탭/정렬
        page.locator("#secStats").scroll_into_view_if_needed(); page.wait_for_timeout(200)
        page.click("#tabCareer"); page.wait_for_timeout(250)
        ok(f"{tag}: 누적 스탯 16명", page.locator("#statRows .strow").count() == 16, f"{page.locator('#statRows .strow').count()}")
        page.click('[data-sort="reb"]'); page.wait_for_timeout(250)
        first = page.locator("#statRows .strow").first.inner_text()
        ok(f"{tag}: 리바운드 정렬", REB_LEAD['name'] in first and str(int(REB_LEAD['reb'])) in first, first.replace("\n", " | "))
        page.screenshot(path=f"{OUT}/{tag}_6_stats.png")
        page.click("#tabEvent"); page.click('[data-sort="pts"]'); page.wait_for_timeout(200)

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
