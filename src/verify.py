# -*- coding: utf-8 -*-
"""로컬 검증: 390x844 / 1280x800 — 잠금 화면, 오답 거부, 정답 입장, 새로고침 유지, 상단 요약 카드 4개 이동,
주차 전환, 검색, 개인 카드, 정/준회원 표기, JS 에러, 가로 스크롤."""
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
ASSOC = [r['name'] for r in DATA['roster'] if r.get('role') == '준회원']
REG_N = sum(1 for r in DATA['roster'] if r.get('role') == '정회원')
REB_LEAD = max(DATA['stats']['career']['rows'], key=lambda r: r['reb'])

# ---- 경기일(일요일) 날씨 예보 픽스처 (Open-Meteo 응답 대체) ----
import datetime, math
TZ = datetime.timezone(datetime.timedelta(hours=9))
WX_DATES = [(datetime.datetime.now(TZ).date() + datetime.timedelta(days=i)) for i in range(8)]
WX_SUN = next(d for d in WX_DATES if d.weekday() == 6)
WX_IDX = WX_DATES.index(WX_SUN)
WX_TS = [f"{WX_SUN.isoformat()}T{h:02d}:00" for h in range(24)]
WX_TEMP = [3 + h * 0.7 for h in range(24)]
WX_PAYLOAD = {
    "daily": {"time": [d.isoformat() for d in WX_DATES], "weather_code": [1] * 8,
              "temperature_2m_max": [10 + i for i in range(8)],
              "temperature_2m_min": [1 + i for i in range(8)],
              "precipitation_probability_max": [10 + i for i in range(8)]},
    "hourly": {"time": WX_TS, "temperature_2m": WX_TEMP, "weather_code": [1] * 24,
               "precipitation_probability": [5] * 24},
}
js_round = lambda v: math.floor(v + 0.5)
WX_HEAD = f"{WX_SUN.month:02d}/{WX_SUN.day:02d}(일) 경기일 예보 · 시흥 대야동"
WX_RANGE = f"{1 + WX_IDX}~{10 + WX_IDX}°C"
WX_PP = f"{10 + WX_IDX}%"
WX_HOURS = " · ".join(f"{h:02d}시 {js_round(WX_TEMP[h])}°" for h in (7, 8, 9, 10))


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

SORT_TOP = {mode: {k: sort_top(v['rows'], k) for k in STAT_KEYS}
            for mode, v in DATA['stats'].items() if isinstance(v, dict) and 'rows' in v}

# ---- 경기 날짜 5개(11/22 · 11/15 · 11/08 · 11/01 · 10/25) 기대값
EVENTS = DATA['stats']['events']
EV = {e['date']: e for e in EVENTS}
EV_ORDER = [e['date'] for e in EVENTS]
EV_LABELS = [e['date'][5:7] + '.' + e['date'][8:10] + ' 경기' + (' · ' + e['tag'] if e.get('tag') else '') for e in EVENTS]
EV_PICK = {e['date']: sorted(e['rows'], key=lambda r: (-(r['pts'] or 0), r['name']))[0] for e in EVENTS}

def fmt_n(v):
    if v is None:
        return '–'
    return str(int(v)) if float(v).is_integer() else ('%g' % v)

def shot_cell(s):
    return '– –' if not s else f"{s['p']:g}% {fmt_n(s['m'])}/{fmt_n(s['a'])}"

def row_cells(r):
    return [fmt_n(r['pts']), fmt_n(r['reb']), fmt_n(r['orb']), fmt_n(r['drb']), fmt_n(r['ast']),
            fmt_n(r['stl']), fmt_n(r['blk']), fmt_n(r['to']), fmt_n(r['pf']),
            shot_cell(r['fg2']), shot_cell(r['fg3']), shot_cell(r['ft']),
            '–' if r['mvp'] is None else f"{r['mvp']:.2f}", fmt_n(r['gp'])]
CARD_P = sorted(DATA['stats']['event']['rows'], key=lambda r: (-r['pts'], r['name']))[0]
CARD_C = [r for r in DATA['stats']['career']['rows'] if r['name'] == CARD_P['name']]
CARD_EXPECT = [f"{CARD_P['fg2']['m']:.0f}/{CARD_P['fg2']['a']:.0f}", f"{CARD_P['fg2']['p']:.0f}%"]
if CARD_C:
    c = CARD_C[0]
    CARD_EXPECT += [f"{c['fg2']['m']:.0f}/{c['fg2']['a']:.0f}", f"{c['fg2']['p']:.0f}%"]

PERQ_KEYS = ['pts', 'reb', 'orb', 'drb', 'ast', 'stl', 'blk', 'to', 'pf']
CELL_P = [r for r in DATA['stats']['event']['rows'] if r['name'] == CELL_PLAYER['name']][0]
EXPECT_Q = [(f"{CELL_P[k] / CELL_P['gp']:.1f}" if CELL_P['gp'] else '–') for k in PERQ_KEYS]
PERQ_TOP = sorted(DATA['stats']['event']['rows'],
                  key=lambda r: (-(r['pts'] / r['gp'] if r['gp'] else -1), r['name']))[0]['name']
CAREER_ROWS = DATA['stats']['career']['rows']
CAREER_P = sorted(CAREER_ROWS, key=lambda r: (-r['pts'], r['name']))[0]
CAREER_Q = [(f"{CAREER_P[k] / CAREER_P['gp']:.1f}" if CAREER_P['gp'] else '–') for k in PERQ_KEYS]
BOTH_ROWS = [r for r in CAREER_ROWS if any(e['name'] == r['name'] for e in DATA['stats']['event']['rows'])]
MODAL_P = sorted(BOTH_ROWS, key=lambda r: (-r['pts'], r['name']))[0]
MODAL_EV = [r for r in DATA['stats']['event']['rows'] if r['name'] == MODAL_P['name']][0]

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

def stub_map(route):
    route.fulfill(status=200, content_type="text/html", body="<title>map</title><h1>지도</h1>")

with sync_playwright() as p:
    browser = p.chromium.launch()
    for tag, w, h in [("m", 390, 844), ("d", 1280, 800)]:
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if tag == "m" else 1,
                                  permissions=["clipboard-read", "clipboard-write"])
        for host in ("**map.naver.com/**", "**map.kakao.com/**", "**play.google.com/**", "**apps.apple.com/**"):
            ctx.route(host, stub_map)
        ctx.route("**api.open-meteo.com/**",
                  lambda route: route.fulfill(status=200, content_type="application/json",
                                              body=json.dumps(WX_PAYLOAD, ensure_ascii=False)))
        page = ctx.new_page()
        errs = []
        collect(page, errs)
        page.goto(URL, wait_until="load")
        page.wait_for_timeout(400)

        # 1) 잠금 화면
        ok(f"{tag}: 잠금 화면 노출", page.locator("#lock").is_visible() and not page.locator(".hero").is_visible())
        page.screenshot(path=f"{OUT}/{tag}_1_lock.png", full_page=False)
        logo = page.evaluate("""() => {
          const s = document.querySelector('.llogo svg');
          if (!s) return null;
          const r = s.getBoundingClientRect(), c = document.querySelector('.lockcard').getBoundingClientRect();
          const ring = s.querySelectorAll('circle')[1];
          return {w: r.width, h: r.height, cx: r.left + r.width / 2, cardCx: c.left + c.width / 2,
                  ring: ring ? ring.getAttribute('stroke') : '', fill: s.querySelector('circle').getAttribute('fill')};
        }""")
        ok(f"{tag}: 게이트 상단 팀 로고(에메랄드 링 + 골드 농구공) 중앙 배치",
           logo and logo["w"] >= 46 and abs(logo["cx"] - logo["cardCx"]) <= 1
           and "51,224,196" in (logo["ring"] or "") and "sbBallGateG" in (logo["fill"] or "")
           and page.locator(".lball").count() == 0,
           str(logo)[:110])
        lsec = page.inner_text(".lsec")
        ok(f"{tag}: 게이트 보안 안내 3줄", page.locator(".lsec li").count() == 3
           and "검색 차단" in lsec and "검색엔진에 조회되지 않습니다" in lsec
           and "암호화 보호" in lsec and "입장 코드로 암호화" in lsec
           and "관리자 반영" in lsec and "본인 기기에만 임시 적용" in lsec,
           " / ".join(lsec.splitlines()))
        ok(f"{tag}: 게이트 안내문 화면 안·가로 넘침 없음", page.evaluate("""() => {
              const ul = document.querySelector('.lsec').getBoundingClientRect();
              return ul.top >= 0 && ul.bottom <= innerHeight + 0.5
                && document.documentElement.scrollWidth <= innerWidth + 1;
            }"""))

        # HTML 소스에 평문 이름이 없는지
        src = page.content()
        ok(f"{tag}: DOM 소스에 평문 이름 없음(ENC만)", not any(n in src for n in NAMES))

        # 2) 오답 거부 → 2회째부터 제한 안내
        page.fill("#code", "1111")
        page.click("#go")
        page.wait_for_timeout(900)
        err = page.inner_text("#lerr")
        ok(f"{tag}: 1회 오답은 일반 안내", ("올바르지" in err) and page.locator("#lock").is_visible(), err)
        page.screenshot(path=f"{OUT}/{tag}_2_wrong.png")
        page.fill("#code", "1112")
        page.click("#go")
        page.wait_for_timeout(900)
        err2 = page.inner_text("#lerr").strip()
        ok(f"{tag}: 2회 오입력 → 제한된 공간 안내",
           err2 == "제한된 공간입니다. 관리자에게 입장코드를 문의해 주세요." and page.locator("#lock").is_visible(), err2)
        page.screenshot(path=f"{OUT}/{tag}_2b_limit.png")
        page.fill("#code", "1113")
        page.click("#go")
        page.wait_for_timeout(900)
        err3 = page.inner_text("#lerr").strip()
        ok(f"{tag}: 3회째도 제한 안내 유지", err3 == "제한된 공간입니다. 관리자에게 입장코드를 문의해 주세요.", err3)

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

        # 3-0) 우측 상단 로고·유튜브 배지
        ytb = page.locator(".hero .ytbadge")
        ok(f"{tag}: 상단 유튜브 배지 1개", ytb.count() == 1 and ytb.is_visible(), f"count={ytb.count()}")
        ok(f"{tag}: 배지 링크 주소·새 창·noopener",
           ytb.get_attribute("href") == "https://www.youtube.com/@stepback_basketball?sub_confirmation=1"
           and ytb.get_attribute("target") == "_blank"
           and "noopener" in (ytb.get_attribute("rel") or "") and "noreferrer" in (ytb.get_attribute("rel") or ""),
           ytb.get_attribute("href") or "")
        intent = ytb.get_attribute("data-yt-intent") or ""
        ok(f"{tag}: 유튜브 앱 intent 링크(구독 파라미터·fallback)",
           intent == "intent://www.youtube.com/@stepback_basketball?sub_confirmation=1#Intent;scheme=https;"
                     "package=com.google.android.youtube;S.browser_fallback_url=https%3A%2F%2Fwww.youtube.com%2F%40stepback_basketball%3Fsub_confirmation%3D1;end",
           intent[:90])
        ok(f"{tag}: 아이폰 앱 스킴(youtube://)",
           (ytb.get_attribute("data-yt-ios") or "").startswith("youtube://www.youtube.com/@stepback_basketball"),
           ytb.get_attribute("data-yt-ios") or "")
        ygeo = page.evaluate("""() => {
          const b = document.querySelector('.hero .ytbadge').getBoundingClientRect();
          const h = document.querySelector('.hero h1').getBoundingClientRect();
          const l = document.querySelector('.heroLeft').getBoundingClientRect();
          const e = document.querySelector('.hero .eyebrow').getBoundingClientRect();
          const p = document.querySelector('.hero .period').getBoundingClientRect();
          const cs = getComputedStyle(document.querySelector('.hero h1'));
          const h1 = document.querySelector('.hero h1');
          return {bx: b.left, by: b.top, bw: b.width, bh: b.height, br: b.right,
                  hx: h.left, hy: h.top, hw: h.width, hh: h.height, hr: h.right,
                  lr: l.right, ex: e.left, py: p.top, ph: p.height,
                  vw: innerWidth, vh: innerHeight, lines: Math.round(h1.getBoundingClientRect().height / parseFloat(cs.lineHeight)),
                  h1ov: h1.scrollWidth - h1.clientWidth,
                  docov: document.documentElement.scrollWidth - innerWidth};
        }""")
        ok(f"{tag}: 배지 우측 상단 배치(뷰포트 안)",
           ygeo["br"] <= ygeo["vw"] - 8 and ygeo["bx"] >= ygeo["vw"] * 0.55
           and ygeo["by"] >= 0 and ygeo["by"] < (130 if w >= 760 else 90)
           and ygeo["bw"] >= 70 and ygeo["bh"] >= 30,
           f"x={ygeo['bx']:.0f}~{ygeo['br']:.0f} y={ygeo['by']:.0f} {ygeo['bw']:.0f}x{ygeo['bh']:.0f} vw={ygeo['vw']}")
        ok(f"{tag}: 배지·제목 겹침 없음(좌우 분리)",
           ygeo["bx"] >= ygeo["hr"] + 4 and ygeo["bx"] >= ygeo["lr"] - 0.5,
           f"badge.left={ygeo['bx']:.1f} h1.right={ygeo['hr']:.1f}")
        ok(f"{tag}: 제목·기간 한 줄 유지(잘림 없음)",
           ygeo["lines"] == 1 and ygeo["h1ov"] <= 0 and ygeo["hw"] >= 140,
           f"lines={ygeo['lines']} ov={ygeo['h1ov']} w={ygeo['hw']:.0f}")
        ok(f"{tag}: 좌측 eyebrow·기간 정상 흐름", ygeo["ex"] < ygeo["bx"] and ygeo["py"] > ygeo["hy"],
           f"eyebrow.x={ygeo['ex']:.0f} period.y={ygeo['py']:.0f}")
        yparts = page.evaluate("""() => {
          const b = document.querySelector('.hero .ytbadge');
          const ball = b.querySelector('svg.ytball'), pl = b.querySelector('svg.pl');
          return {name: (b.querySelector('.ytname')||{}).textContent || '',
                  play: (b.querySelector('.ytplay')||{}).innerText || '',
                  ball: !!ball && ball.getBoundingClientRect().width > 15,
                  pl: !!pl && pl.getBoundingClientRect().width > 8};
        }""")
        ok(f"{tag}: 배지 구성(농구공·STEPBACK·YouTube 구독 ↗)",
           yparts["ball"] and yparts["pl"] and yparts["name"].strip() == "STEPBACK"
           and "YouTube 구독" in yparts["play"] and "↗" in yparts["play"],
           f"{yparts}")
        prevented = page.evaluate("""() => {
          const a = document.querySelector('.hero .ytbadge');
          const ev = new MouseEvent('click', {bubbles: true, cancelable: true});
          a.dispatchEvent(ev);
          return ev.defaultPrevented;
        }""")
        ok(f"{tag}: iOS·PC는 기본 https 새 탭 동작(가로채지 않음)", prevented is False and "Android" not in page.evaluate("navigator.userAgent"),
           f"defaultPrevented={prevented}")
        ytb.screenshot(path=f"{OUT}/{tag}_3a_ytbadge.png")
        page.locator(".heroTop").screenshot(path=f"{OUT}/{tag}_3a2_herotop.png")

        # 3-0b) 구장 배지 → 길찾기 시트(주소 복사 + 네이버지도·카카오맵·티맵)
        gym = page.locator("#gymBtn")
        ok(f"{tag}: 구장 배지는 버튼(길찾기)", gym.evaluate("el=>el.tagName") == "BUTTON"
           and gym.get_attribute("aria-haspopup") == "dialog"
           and gym.get_attribute("aria-controls") == "navModal"
           and "시흥 SH스포츠센터" in gym.inner_text(), gym.inner_text().replace("\n", " "))
        gym.click(); page.wait_for_timeout(400)
        ok(f"{tag}: 길찾기 시트 열림", not page.locator("#navModal").is_hidden())
        page.wait_for_selector("#navWx.ok", timeout=6000)
        wx = page.inner_text("#navWx")
        ok(f"{tag}: 경기일(일요일) 예보 헤더", WX_HEAD in wx and "🌤️" in wx, wx.splitlines()[0] if wx else "")
        ok(f"{tag}: 예보 수치 — 날씨·기온·강수확률", "대체로 맑음" in wx and WX_RANGE in wx and WX_PP in wx
           and "강수확률" in wx, wx.replace("\n", " | "))
        ok(f"{tag}: 오전 07~10시 시간대 기온", WX_HOURS in wx, wx.splitlines()[-1] if wx else "")
        ok(f"{tag}: 날씨 카드가 주소 박스 위·넘침 없음", page.evaluate("""() => {
              const w = document.querySelector('#navWx').getBoundingClientRect();
              const g = document.querySelector('#navModal .nvgym').getBoundingClientRect();
              const sh = document.querySelector('#navModal .sheet');
              return w.bottom <= g.top + 0.5 && sh.scrollWidth <= sh.clientWidth + 1;
            }"""))
        ok(f"{tag}: 시트 — 구장명·주소", page.inner_text("#navModal .nvgym .gname") == "시흥 SH스포츠센터"
           and page.inner_text("#navModal .nvgym .gaddr") == "경기도 시흥시 대야동 500-2")
        page.click("#addrCopy"); page.wait_for_timeout(350)
        ok(f"{tag}: 주소 복사 → 클립보드·안내",
           page.evaluate("navigator.clipboard.readText()") == "경기도 시흥시 대야동 500-2"
           and "복사" in page.inner_text("#addrStat"), page.inner_text("#addrStat"))
        navs = page.eval_on_selector_all("#navPick [data-nav]", "els=>els.map(e=>[e.dataset.nav, e.dataset.app, e.dataset.web||''])")
        NAV_EXPECT = {
            "naver": ("nmap://route/car?dlat=37.4418653&dlng=126.7873274&dname=%EC%8B%9C%ED%9D%A5%20SH%EC%8A%A4%ED%8F%AC%EC%B8%A0%EC%84%BC%ED%84%B0&appname=stepback-basketball",
                      "https://map.naver.com/p/search/%EA%B2%BD%EA%B8%B0%EB%8F%84%20%EC%8B%9C%ED%9D%A5%EC%8B%9C%20%EB%8C%80%EC%95%BC%EB%8F%99%20500-2"),
            "kakao": ("kakaomap://route?ep=37.4418653,126.7873274&by=CAR",
                      "https://map.kakao.com/link/to/%EC%8B%9C%ED%9D%A5%20SH%EC%8A%A4%ED%8F%AC%EC%B8%A0%EC%84%BC%ED%84%B0,37.4418653,126.7873274"),
            "tmap": ("tmap://route?goalname=%EC%8B%9C%ED%9D%A5%20SH%EC%8A%A4%ED%8F%AC%EC%B8%A0%EC%84%BC%ED%84%B0&goalx=126.7873274&goaly=37.4418653", ""),
        }
        got_nav = {n: (a, w_) for n, a, w_ in navs}
        ok(f"{tag}: 내비 3종 딥링크·웹 fallback 정확", got_nav == NAV_EXPECT, f"{list(got_nav)}")
        page.screenshot(path=f"{OUT}/{tag}_3c_nav_sheet.png")
        pops = []
        page.on("popup", lambda pp: pops.append(pp.url))
        page.click("#navPick [data-nav='naver']"); page.wait_for_timeout(700)
        ok(f"{tag}: PC 네이버지도 → 웹 지도 새 탭", any("map.naver.com/p/search" in u for u in pops), f"{pops[:1]}")
        page.click("#navPick [data-nav='tmap']"); page.wait_for_timeout(600)
        ok(f"{tag}: PC 티맵 → 앱 안내", "모바일 앱" in page.inner_text("#navNote"), page.inner_text("#navNote"))
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        ok(f"{tag}: 길찾기 시트 닫기(Esc)", page.locator("#navModal").is_hidden())
        ok(f"{tag}: 시트 안내문 잘림 없음(끝까지 스크롤 시 보임)", page.evaluate("""() => {
              const sh = document.querySelector('#navModal .sheet');
              sh.scrollTop = sh.scrollHeight;
              const n = document.querySelector('#navNote').getBoundingClientRect();
              const r = sh.getBoundingClientRect();
              return n.bottom <= r.bottom + 1 && n.top >= r.top - 1
                && sh.scrollWidth <= sh.clientWidth + 1;
            }"""))

        # 3-0c) 네이버 밴드 바로가기 — 유튜브 배지 아래 stack
        bnd = page.locator(".hero .bandbadge")
        BAND = "https://band.us/band/63120390"
        ok(f"{tag}: BAND 배지 1개(유튜브 아래 stack)", bnd.count() == 1 and bnd.is_visible()
           and "BAND 바로가기" in bnd.inner_text() and "↗" in bnd.inner_text(), bnd.inner_text().replace("\n", " "))
        bgeo = page.evaluate("""() => {
          const y = document.querySelector('.hero .ytbadge').getBoundingClientRect();
          const b = document.querySelector('.hero .bandbadge').getBoundingClientRect();
          const h = document.querySelector('.hero h1').getBoundingClientRect();
          const p = document.querySelector('.hero .period').getBoundingClientRect();
          return {b: [b.left, b.right, b.top, b.bottom], yb: y.bottom, hr: h.right, pb: p.bottom, br: b.bottom,
                  vw: innerWidth, doc: document.documentElement.scrollWidth};
        }""")
        bl, br_, bt, bb = bgeo["b"]
        ok(f"{tag}: BAND 배지 위치 — 유튜브 아래·뷰포트 안·겹침 없음",
           bt >= bgeo["yb"] - 1 and br_ <= bgeo["vw"] - 6 and bl >= bgeo["hr"] - 0.5 and bl >= bgeo["vw"] * 0.5,
           f"band x={bl:.0f}~{br_:.0f} y={bt:.0f}~{bb:.0f} yt.bottom={bgeo['yb']:.0f} h1.right={bgeo['hr']:.0f}")
        ok(f"{tag}: BAND 링크·새 창·noopener·intent·ios 스킴",
           bnd.get_attribute("href") == BAND and bnd.get_attribute("target") == "_blank"
           and "noopener" in (bnd.get_attribute("rel") or "") and "noreferrer" in (bnd.get_attribute("rel") or "")
           and bnd.get_attribute("data-band-intent") == "intent://band.us/band/63120390#Intent;scheme=https;"
                "package=com.nhn.android.band;S.browser_fallback_url=https%3A%2F%2Fband.us%2Fband%2F63120390;end"
           and bnd.get_attribute("data-band-ios") == "bandapp://band/63120390",
           bnd.get_attribute("data-band-intent") or "")
        ok(f"{tag}: PC는 BAND 기본 https 새 탭 동작", page.evaluate("""() => {
              const a = document.querySelector('.hero .bandbadge');
              const ev = new MouseEvent('click', {bubbles: true, cancelable: true});
              a.dispatchEvent(ev); return ev.defaultPrevented;
            }""") is False)

        # 3-1) 상단 요약 카드 4개 — 클릭 이동 · 라벨 잘림 없음
        cards = page.locator("#heroStats .stat")
        ok(f"{tag}: 요약 카드 4개(버튼)", cards.count() == 4 and page.eval_on_selector_all("#heroStats .stat", "els=>els.every(e=>e.tagName==='BUTTON')"),
           f"count={cards.count()}")
        lab = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('#heroStats .stat').forEach(el => {
            const k = el.querySelector('.k');
            const r = document.createRange(); r.selectNodeContents(k);
            const cr = el.getBoundingClientRect(), kr = k.getBoundingClientRect(), tr = r.getBoundingClientRect();
            out.push({ txt: k.textContent, leftMargin: tr.left - cr.left, rightMargin: cr.right - tr.right,
                       lines: Math.round(kr.height / parseFloat(getComputedStyle(k).lineHeight)),
                       overflow: k.scrollWidth - k.clientWidth });
          });
          return out;
        }""")
        ok(f"{tag}: 요약 카드 라벨 한 줄·좌우 여백",
           all(x["lines"] == 1 and x["leftMargin"] >= 3 and x["rightMargin"] >= 3 and x["overflow"] <= 0 for x in lab),
           "; ".join(f"{x['txt']}: {x['leftMargin']:.1f}/{x['rightMargin']:.1f}" for x in lab))
        if w < 760:
            page.locator("#heroStats").screenshot(path=f"{OUT}/{tag}_3b_hero_cards.png")

        def near_top(sel, tol=14):
            return page.eval_on_selector(sel, "el=>el.getBoundingClientRect().top")

        def to_top():
            page.evaluate("window.scrollTo(0,0)"); page.wait_for_timeout(250)

        # 정규 → 최종 승률 섹션
        to_top(); cards.nth(0).click(); page.wait_for_timeout(900)
        t = near_top("#secRank")
        ok(f"{tag}: '정규' 카드 → 최종 승률 섹션", page.evaluate("window.scrollY") > 100 and -2 <= t <= 70, f"top={t:.0f}")

        # 경기 → 주간 결과 전체 섹션
        to_top(); cards.nth(1).click(); page.wait_for_timeout(1200)
        t = near_top("#secWeeks")
        ok(f"{tag}: '경기' 카드 → 주간 결과 전체 섹션", page.evaluate("window.scrollY") > 100 and -2 <= t <= 70, f"top={t:.0f}")

        # 게스트 → 접혀 있으면 펼치고 게스트 섹션
        page.evaluate("document.querySelector('#guestBox').open=false"); to_top()
        cards.nth(2).click(); page.wait_for_timeout(1000)
        t = near_top("#guestBox")
        ok(f"{tag}: '게스트' 카드 → 펼침+게스트 섹션",
           page.eval_on_selector("#guestBox", "el=>el.open") and -2 <= t <= 70,
           f"open={page.eval_on_selector('#guestBox','el=>el.open')} top={t:.0f}")
        ok(f"{tag}: 게스트 목록 채워짐", page.locator("#guestRows .grow").count() == len(DATA['guests']),
           f"{page.locator('#guestRows .grow').count()}")

        # 최고 승률 → 그 선수 개인 카드
        to_top(); cards.nth(3).click()
        page.wait_for_selector("#modal:not([hidden])", timeout=4000)
        ok(f"{tag}: '최고 승률' 카드 → {TOP['name']} 개인 카드",
           page.inner_text("#mName").find(TOP['name']) >= 0 and f"{TOP['rate']}" in page.inner_text("#mBody"),
           page.inner_text("#mName"))
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
        to_top()

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

        # 10) 개인 스탯 — 3모드(시즌 누적 / 시즌 누적(쿼터당) / 직전 경기) · 정렬 · 스크롤
        page.locator("#secStats").scroll_into_view_if_needed(); page.wait_for_timeout(250)
        heads = page.eval_on_selector_all("#statHead th", r"els=>els.map(e=>e.innerText.replace(/[\s\u25bc]/g,''))")
        ok(f"{tag}: 스탯 헤더 15열", heads == STAT_HEADS, " / ".join(heads))
        ok(f"{tag}: 정렬 칩 {len(STAT_KEYS) - len(SHOT_KEYS)}개", page.locator("#sortRow .sortchip").count() == len(STAT_KEYS) - len(SHOT_KEYS), f"{page.locator('#sortRow .sortchip').count()}")
        labels = page.eval_on_selector_all("#statTabs button", "els=>els.map(e=>e.innerText.trim())")
        ok(f"{tag}: 스탯 모드 순서", labels == ['시즌 누적', '시즌 누적(쿼터당)', '직전 경기'], " > ".join(labels))
        ok(f"{tag}: 기본 시즌 누적 · 날짜 선택 숨김",
           page.get_attribute("#tabCareer", "aria-pressed") == "true"
           and page.locator("#statRows .strow").count() == len(DATA['stats']['career']['rows'])
           and page.locator("#evWrap").is_hidden(),
           f"rows={page.locator('#statRows .strow').count()}")

        # ② 시즌 누적(쿼터당)
        page.click("#tabCareerQ"); page.wait_for_timeout(350)
        sel_row = f"#statRows .strow[data-person='{CAREER_P['name']}']"
        qcells = page.eval_on_selector(sel_row, "tr=>Array.from(tr.children).slice(1,10).map(td=>td.innerText.trim())")
        ok(f"{tag}: 시즌 누적(쿼터당) 9항목 평균", qcells == CAREER_Q, f"{qcells} vs {CAREER_Q}")
        shot_txt = page.eval_on_selector(f"{sel_row} td.shot", "el=>el.innerText.replace(/\\s+/g,' ')")
        ok(f"{tag}: 2점 % 유지 + 쿼터당 성공/시도", '%' in shot_txt and '/Q' in shot_txt, shot_txt)
        page.screenshot(path=f"{OUT}/{tag}_6c1_stats_careerq.png")

        # ③ 직전 경기 (+ 날짜 드롭다운)
        page.click("#tabEvent"); page.wait_for_timeout(400)
        ok(f"{tag}: 직전 경기 15행 · 날짜 선택 노출",
           page.locator("#statRows .strow").count() == 15 and page.locator("#evWrap").is_visible()
           and page.eval_on_selector("#evSel", "el=>el.options[el.selectedIndex].text").strip() == '11.22 경기',
           f"rows={page.locator('#statRows .strow').count()}")
        ok(f"{tag}: 행당 15칸", page.locator("#statRows .strow").first.locator("td").count() == 14,
           f"tds={page.locator('#statRows .strow').first.locator('td').count()}")
        cells = page.eval_on_selector(f"#statRows .strow[data-person='{CELL_PLAYER['name']}']",
                                      "tr=>Array.from(tr.children).slice(1).map(td=>td.innerText.replace(/\\s+/g,' ').trim())")
        ok(f"{tag}: {CELL_PLAYER['name']} 전 항목 셀 값", cells == CELL_EXPECT, " | ".join(cells))

        # ③-2) 경기 날짜 5개 드롭다운 — 11.22 · 11.15 · 11.08 · 11.01 · 10.25
        opts = page.eval_on_selector_all("#evSel option", "els=>els.map(e=>[e.value, e.textContent.trim()])")
        ok(f"{tag}: 경기 날짜 5개(최신순)", [o[0] for o in opts] == EV_ORDER and [o[1] for o in opts] == EV_LABELS,
           " / ".join(o[1] for o in opts))
        for d in EV_ORDER:
            page.select_option("#evSel", d)
            page.wait_for_timeout(300)
            ev, pick = EV[d], EV_PICK[d]
            n = page.locator("#statRows .strow").count()
            got = page.eval_on_selector(f"#statRows .strow[data-person='{pick['name']}']",
                                        "tr=>Array.from(tr.children).slice(1).map(td=>td.innerText.replace(/\\s+/g,' ').trim())")
            exp = row_cells(pick)
            asof = page.inner_text("#statAsOf")
            lab = EV_LABELS[EV_ORDER.index(d)]
            ok(f"{tag}: {d} — {n}명 · {pick['name']} 전 항목",
               n == len(ev['rows']) and got == exp and lab in asof,
               (f"{got} vs {exp}" if got != exp else f"{n}명 · {asof[:40]}"))
            if pick['mvp'] is None:
                ok(f"{tag}: {d} MVP 포인트 없음 '–'", got[12] == '–', got[12])
        # 총합 ↔ 쿼터당 (MVP 없는 날짜 포함)
        for d in ('2026-11-08', '2026-11-01', '2026-10-25'):
            page.select_option("#evSel", d); page.wait_for_timeout(250)
            pick = EV_PICK[d]
            page.click("#evView [data-evview='perq']"); page.wait_for_timeout(300)
            q = page.eval_on_selector(f"#statRows .strow[data-person='{pick['name']}']",
                                      "tr=>Array.from(tr.children).slice(1,10).map(td=>td.innerText.trim())")
            qe = ['–' if pick[k] is None else (f"{pick[k] / pick['gp']:.1f}" if pick['gp'] else '–') for k in PERQ_KEYS]
            ok(f"{tag}: {d} 쿼터당 9항목", q == qe, f"{q} vs {qe}")
            page.click("#evView [data-evview='total']"); page.wait_for_timeout(250)
            back = page.eval_on_selector(f"#statRows .strow[data-person='{pick['name']}']",
                                         "tr=>Array.from(tr.children).slice(1).map(td=>td.innerText.replace(/\\s+/g,' ').trim())")
            ok(f"{tag}: {d} 총합 복귀", back == row_cells(pick), f"{back}")

        # ③-3) 정렬 칩 → 해당 열이 '선수' 고정 열 옆으로 자동 스크롤
        page.select_option("#evSel", EV_ORDER[0]); page.wait_for_timeout(250)
        if w < 760:
            page.eval_on_selector("#statScroll", "el=>{el.scrollLeft=0}"); page.wait_for_timeout(200)
            page.click("#sortRow [data-sort='to']"); page.wait_for_timeout(1100)
            m = page.evaluate("""() => {
              const sc = document.querySelector('#statScroll');
              const th = document.querySelector('#statHead th[data-col="to"]');
              const pc = document.querySelector('#statHead th.pcol');
              const a = th.getBoundingClientRect(), b = pc.getBoundingClientRect(), c = sc.getBoundingClientRect();
              return {thL: a.left, thR: a.right, pinR: b.right, scL: c.left, scR: c.right, sl: sc.scrollLeft, sw: sc.scrollWidth, cw: sc.clientWidth};
            }""")
            ok(f"{tag}: 턴오버 칩 → 표 자동 가로 스크롤", m["sl"] > 120
               and m["pinR"] - 4 <= m["thL"] <= m["pinR"] + 26 and m["thL"] < m["scR"],
               f"scrollLeft={m['sl']} th.left={m['thL']:.0f} pin.right={m['pinR']:.0f}")
            page.screenshot(path=f"{OUT}/{tag}_6c3_chip_scroll_to.png")
            page.eval_on_selector("#statScroll", "el=>{el.scrollLeft=0}"); page.wait_for_timeout(200)
            page.click("#sortRow [data-sort='pts']"); page.wait_for_timeout(900)
            sl0 = page.eval_on_selector("#statScroll", "el=>el.scrollLeft")
            ok(f"{tag}: 맨 앞 열(득점) 칩 → 스크롤 0 복귀", sl0 <= 2, f"scrollLeft={sl0}")

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

        # 헤더 클릭 정렬 — 14개 열 전부(직전 경기 기준)
        for key in STAT_KEYS:
            page.click(f"#statHead [data-sort='{key}']"); page.wait_for_timeout(120)
            top = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
            exp = SORT_TOP['event'][key]
            ok(f"{tag}: 헤더 정렬 {key} → {exp}", top == exp, f"got {top}")
            if key == 'stl':
                page.screenshot(path=f"{OUT}/{tag}_6c_stats_sort_stl.png")

        # 직전 경기 — 쿼터당 보조 토글
        page.click("#evView [data-evview='perq']"); page.wait_for_timeout(300)
        qcells = page.eval_on_selector(sel_row := f"#statRows .strow[data-person='{CELL_PLAYER['name']}']",
                                       "tr=>Array.from(tr.children).slice(1,10).map(td=>td.innerText.trim())")
        ok(f"{tag}: 직전 경기 쿼터당 9항목 평균", qcells == EXPECT_Q, f"{qcells} vs {EXPECT_Q}")
        page.click("#statHead [data-sort='pts']"); page.wait_for_timeout(250)
        top = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
        ok(f"{tag}: 쿼터당 수치 기준 정렬(득점/Q) → {PERQ_TOP}", top == PERQ_TOP, top)
        page.screenshot(path=f"{OUT}/{tag}_6c2_stats_perq.png")
        page.click("#evView [data-evview='total']"); page.wait_for_timeout(250)
        back = page.eval_on_selector(sel_row, "tr=>Array.from(tr.children).slice(1,10).map(td=>td.innerText.trim())")
        ok(f"{tag}: 직전 경기 총합 복귀", back == CELL_EXPECT[:9], f"{back}")

        # 시즌 누적 복귀 + 칩 정렬
        page.click("#tabCareer"); page.wait_for_timeout(300)
        ok(f"{tag}: 누적 스탯 16명", page.locator("#statRows .strow").count() == 16, f"{page.locator('#statRows .strow').count()}")
        page.click("#sortRow [data-sort='reb']"); page.wait_for_timeout(250)
        first = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
        ok(f"{tag}: 리바운드 정렬", first == REB_LEAD['name'], first)
        page.click("#sortRow [data-sort='to']"); page.wait_for_timeout(200)
        first = page.eval_on_selector("#statRows .strow th.pcol b", "el=>el.innerText.trim()")
        ok(f"{tag}: 턴오버 정렬", first == SORT_TOP['career']['to'], first)
        page.screenshot(path=f"{OUT}/{tag}_6d_stats_career.png")

        # 개인 카드(모달) — 같은 3모드
        page.click("#sortRow [data-sort='pts']"); page.wait_for_timeout(200)
        page.locator(f"#statRows .strow[data-person='{MODAL_P['name']}']").click()
        page.wait_for_selector("#modal:not([hidden])", timeout=4000)
        mb = page.inner_text("#mBody")
        need = ["2점", "3점", "자유투", "득점", "리바운드", "ORB", "DRB", "어시스트", "스틸", "블락", "턴오버", "파울", "MVP", "출전", "평균(점/Q)"]
        ok(f"{tag}: 개인 카드 전 항목 표시", all(k in mb for k in need), "".join(k for k in need if k not in mb) or "all")

        def msc():
            return {k: v for k, v in page.evaluate("""() => [...document.querySelectorAll('#mStatBody .msc')]
              .map(e => [e.querySelector('.k').innerText.trim(), e.querySelector('.v').innerText.trim()])""")}

        mlabels = page.eval_on_selector_all("#mBody .mtabs button", "els=>els.map(e=>e.innerText.trim())")
        ok(f"{tag}: 카드 모드 순서", mlabels == ['시즌 누적', '시즌 누적(쿼터당)', '직전 경기'], " > ".join(mlabels))
        tot = msc()
        ok(f"{tag}: 카드 기본 시즌 누적 평균(점/Q)", tot.get('평균(점/Q)') == f"{MODAL_P['ppg']:.1f}"
           and tot.get('득점') == f"{MODAL_P['pts']:g}", f"득점={tot.get('득점')} avg={tot.get('평균(점/Q)')}")
        page.click("#mBody .mtabs button[data-mdmode='careerQ']"); page.wait_for_timeout(300)
        pq = msc()
        ok(f"{tag}: 카드 시즌 누적(쿼터당) 9항목",
           pq.get('득점 /Q') == f"{MODAL_P['pts'] / MODAL_P['gp']:.1f}"
           and pq.get('리바운드 /Q') == f"{MODAL_P['reb'] / MODAL_P['gp']:.1f}"
           and pq.get('스틸 /Q') == f"{MODAL_P['stl'] / MODAL_P['gp']:.1f}"
           and pq.get('파울 /Q') == f"{MODAL_P['pf'] / MODAL_P['gp']:.1f}",
           f"득점={pq.get('득점 /Q')} 리바={pq.get('리바운드 /Q')} 파울={pq.get('파울 /Q')}")
        ok(f"{tag}: 쿼터당 모드 평균(점/Q) 카드 생략", '평균(점/Q)' not in pq)
        shots_pq = page.eval_on_selector_all("#mStatBody .mshotc .pq", "els=>els.map(e=>e.innerText.trim())")
        ok(f"{tag}: 2·3점·자유투 % 유지 + /Q 성공/시도", len(shots_pq) >= 1 and '%' in page.inner_text("#mStatBody .mshots"), f"{shots_pq}")
        page.screenshot(path=f"{OUT}/{tag}_6f_modal_perq.png")
        page.click("#mBody .mtabs button[data-mdmode='event']"); page.wait_for_timeout(300)
        ev = msc()
        ok(f"{tag}: 카드 직전 경기 평균(점/Q)", ev.get('평균(점/Q)') == f"{MODAL_EV['ppg']:.1f}"
           and ev.get('득점') == f"{MODAL_EV['pts']:g}", f"득점={ev.get('득점')} avg={ev.get('평균(점/Q)')}")
        # 카드 안 경기 날짜 드롭다운 — 5개 날짜 전환
        mopts = page.eval_on_selector_all("#mEvSel option", "els=>els.map(e=>e.textContent.trim())")
        ok(f"{tag}: 카드 경기 날짜 5개", mopts == EV_LABELS, " / ".join(mopts))
        if page.locator("#mEvSel option[value='2026-10-25']").count():
            page.select_option("#mEvSel", "2026-10-25"); page.wait_for_timeout(350)
            mb2 = page.inner_text("#mStatBody")
            pick = [r for r in EV['2026-10-25']['rows'] if r['name'] == MODAL_P['name']]
            if pick:
                p = pick[0]
                got = msc()
                ok(f"{tag}: 카드 10.25(3G) 전환", "10.25 경기 · 3G" in mb2 and got.get('득점') == fmt_n(p['pts'])
                   and got.get('출전') == fmt_n(p['gp']) and got.get('MVP') == ('–' if p['mvp'] is None else f"{p['mvp']:.2f}"),
                   f"{mb2.splitlines()[0][:40]} 득점={got.get('득점')} MVP={got.get('MVP')}")
                page.click("#mEvView [data-mdview='perq']"); page.wait_for_timeout(300)
                gq = msc()
                ok(f"{tag}: 카드 10.25 쿼터당", gq.get('득점 /Q') == f"{p['pts'] / p['gp']:.1f}", f"{gq.get('득점 /Q')}")
                page.click("#mEvView [data-mdview='total']"); page.wait_for_timeout(250)
            page.screenshot(path=f"{OUT}/{tag}_6e2_modal_1025.png")
        page.screenshot(path=f"{OUT}/{tag}_6e_stats_modal.png")
        page.keyboard.press("Escape"); page.wait_for_timeout(250)

        # 11) 로스터
        page.locator("#secRoster").scroll_into_view_if_needed()
        ok(f"{tag}: 로스터 21명", page.locator("#rosterGrid .rcell").count() == 21, f"{page.locator('#rosterGrid .rcell').count()}")
        rsum = page.inner_text("#rosterSum")
        ok(f"{tag}: 로스터 정회원 {REG_N} · 준회원 {len(ASSOC)} 배지",
           f"정회원 {REG_N}명" in rsum and f"준회원 {len(ASSOC)}명" in rsum, rsum.replace("\n", " "))
        page.click('[data-pos="ASSOC"]'); page.wait_for_timeout(250)
        ok(f"{tag}: 준회원 필터 {len(ASSOC)}명", page.locator("#rosterGrid .rcell").count() == len(ASSOC)
           and page.locator("#rosterGrid .rcell.assoc .rrole").count() == len(ASSOC),
           f"{page.locator('#rosterGrid .rcell').count()} / 배지 {page.locator('#rosterGrid .rcell.assoc .rrole').count()}")
        page.screenshot(path=f"{OUT}/{tag}_7b_assoc.png")
        page.click('[data-pos="ALL"]'); page.wait_for_timeout(200)
        ok(f"{tag}: 로스터 준회원 카드 배지", page.locator("#rosterGrid .rcell.assoc").count() == len(ASSOC),
           f"{page.locator('#rosterGrid .rcell.assoc').count()}")
        if ASSOC:
            page.locator("#rosterGrid .rcell.assoc").first.click()
            page.wait_for_selector("#modal:not([hidden])", timeout=4000)
            ok(f"{tag}: 준회원 개인 카드 이름 옆 배지", "준회원" in page.inner_text("#mName"), page.inner_text("#mName"))
            ok(f"{tag}: 준회원 개인 카드 승률/기록", "승률" in page.inner_text("#mBody"))
            page.screenshot(path=f"{OUT}/{tag}_7c_assoc_modal.png")
            page.keyboard.press("Escape"); page.wait_for_timeout(250)
        page.click('[data-pos="PG"]'); page.wait_for_timeout(250)
        ok(f"{tag}: PG 필터 4명", page.locator("#rosterGrid .rcell").count() == 4, f"{page.locator('#rosterGrid .rcell').count()}")
        page.screenshot(path=f"{OUT}/{tag}_7_roster.png")
        page.click('[data-pos="ALL"]')

        # 12) 주간 아코디언 45개 + 펼치기
        ok(f"{tag}: 주간 카드 45개", page.locator("#weekList .wkcard").count() == 45)
        page.locator('#weekList .wkcard').nth(1).locator("summary").click()
        page.wait_for_timeout(250)
        ok(f"{tag}: 주간 펼침", page.locator('#weekList .wkcard').nth(1).get_attribute("open") is not None)

        # 12-1) 개인 상세정보(키·넘버·포지션) 입력·업데이트 + 카톡 복사 — 정회원·준회원 / 게스트 제외
        NO_NUM = [r['name'] for r in DATA['roster'] if r.get('no') in (None, '')]
        REG_NM, ASSOC_NM = '김영익', ASSOC[0]
        GST_NM = DATA['guests'][0]['name']

        def open_card(nm):
            page.evaluate("document.querySelector('#modal').hidden=true;document.body.style.overflow=''")
            page.evaluate("""(n) => {
              const el = document.querySelector(`#rosterGrid [data-person="${n}"]`)
                || document.querySelector(`#statRows [data-person="${n}"]`);
              el.click();
            }""", nm)
            page.wait_for_selector("#modal:not([hidden])", timeout=4000)
            page.wait_for_timeout(220)

        open_card(REG_NM)
        ok(f"{tag}: 정회원 카드 — '개인정보 업데이트하기' 버튼", page.locator("#pInfoSlot .openbtn").count() == 1
           and "개인정보 업데이트하기" in page.inner_text("#pInfoSlot"), page.inner_text("#pInfoSlot"))
        ok(f"{tag}: 카드 배지 #24 · 181cm · SF/PF", page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()") == "#24 · 181cm · SF/PF",
           page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()"))
        page.click("#pInfoSlot [data-popen]"); page.wait_for_timeout(200)
        ok(f"{tag}: 폼 — 이름 고정·키·넘버·없음·포지션 5종", page.locator("#pInfo").count() == 1
           and page.inner_text("#pInfo .fixed") == REG_NM and page.input_value("#pHeight") == "181"
           and page.input_value("#pNumber") == "24" and page.locator("#pInfo [data-ppos]").count() == 5)
        ok(f"{tag}: 폼에 임시 적용 안내", "현재 기기에만 임시 적용" in page.inner_text("#pInfo") and "스텝백 카톡방(관리자)" in page.inner_text("#pInfo"))
        page.fill("#pHeight", "189"); page.fill("#pNumber", "32")
        page.click("#pInfo [data-ppos='PF']"); page.click("#pInfo [data-ppos='C']")
        page.click("#pInfo [data-psave]"); page.wait_for_timeout(400)
        ok(f"{tag}: 저장 → 카드 배지 즉시 반영(#32 · 189cm · SF/C)",
           page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()") == "#32 · 189cm · SF/C",
           page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()"))
        ok(f"{tag}: 복사 안내 + 양식(수동 복사 박스)", page.inner_text("#pCopyBox p") == "아래 양식을 스텝백 카톡방에 공유해 주세요."
           and page.input_value("#pCopy") == f"스텝백 정보 업데이트 요청 드립니다.\n[{REG_NM} / 189cm / 32번 / SF/C]",
           repr(page.input_value("#pCopy")))
        ok(f"{tag}: 복사 영역 임시 적용 안내", "현재 기기에만 임시 적용" in page.inner_text("#pCopyBox .note"))
        ok(f"{tag}: localStorage stepback-profile-v1 저장", REG_NM in (page.evaluate("localStorage.getItem('stepback-profile-v1')") or ""))
        page.screenshot(path=f"{OUT}/{tag}_12a_prof_saved.png")
        page.keyboard.press("Escape"); page.wait_for_timeout(200)
        ok(f"{tag}: 로스터·스탯 표 메타 즉시 반영",
           "189cm" in page.eval_on_selector(f"#rosterGrid [data-person='{REG_NM}'] .nmn span", "el=>el.innerText")
           and page.eval_on_selector(f"#statRows .strow[data-person='{REG_NM}'] .who i", "el=>el.innerText") == "#32 · 189cm · SF/C")
        for nm in NO_NUM:
            ro = [r for r in DATA['roster'] if r['name'] == nm][0]
            open_card(nm)
            ok(f"{tag}: {nm} — '개인정보 업데이트하기'(번호없음 확정, 자동 오픈 없음)",
               page.locator("#pInfoSlot .openbtn").count() == 1 and page.locator("#pInfo").count() == 0)
            ok(f"{tag}: {nm} 배지 '번호없음 · {ro['height']}cm · {ro['pos']}'",
               page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()") == f"번호없음 · {ro['height']}cm · {ro['pos']}",
               page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()"))
            page.click("#pInfoSlot [data-popen]"); page.wait_for_timeout(180)
            ok(f"{tag}: {nm} 폼 — 없음 체크·넘버 비활성",
               page.is_checked("#pNumNone") and page.eval_on_selector("#pNumber", "el=>el.disabled"))
            page.keyboard.press("Escape"); page.wait_for_timeout(150)
            ok(f"{tag}: 로스터 {nm} 번호칸 '없음'", page.eval_on_selector(f"#rosterGrid [data-person='{nm}'] .no", "el=>el.innerText").strip() == "없음")
        open_card(ASSOC_NM)
        ok(f"{tag}: 준회원({ASSOC_NM})도 '개인정보 업데이트하기'", page.locator("#pInfoSlot .openbtn").count() == 1)
        page.keyboard.press("Escape"); page.wait_for_timeout(150)
        def open_guest(nm):
            page.evaluate("""(n) => { document.querySelector('#guestBox').open = true;
              [...document.querySelectorAll('#guestRows .grow')].find(e => e.dataset.person === n).click(); }""", nm)
            page.wait_for_selector("#modal:not([hidden])", timeout=4000)
            page.wait_for_timeout(220)

        open_guest(GST_NM)
        ok(f"{tag}: 게스트({GST_NM}) 카드 — '정보 입력하기' 버튼(자동 오픈 없음)",
           page.locator("#pInfoSlot .openbtn").count() == 1 and page.locator("#pInfo").count() == 0
           and page.inner_text("#pInfoSlot").strip() == "정보 입력하기" and page.eval_on_selector("#mProf", "el=>el.hidden"),
           page.inner_text("#pInfoSlot"))
        page.click("#pInfoSlot [data-popen]"); page.wait_for_timeout(200)
        ok(f"{tag}: 게스트 폼 — 이름 고정·'다음에 하기'", page.inner_text("#pInfo .fixed") == GST_NM
           and page.inner_text("#pInfo [data-pclose]") == "다음에 하기")
        page.fill("#pHeight", "180"); page.fill("#pNumber", "88")
        page.click("#pInfo [data-ppos='SG']")
        page.click("#pInfo [data-psave]"); page.wait_for_timeout(400)
        ok(f"{tag}: 게스트 카드 배지 반영(#88 · 180cm · SG)",
           page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()") == "#88 · 180cm · SG",
           page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()"))
        ok(f"{tag}: 게스트 카톡 양식 동일 형식",
           page.input_value("#pCopy") == f"스텝백 정보 업데이트 요청 드립니다.\n[{GST_NM} / 180cm / 88번 / SG]",
           repr(page.input_value("#pCopy")))
        page.screenshot(path=f"{OUT}/{tag}_12b_guest_saved.png")
        page.keyboard.press("Escape"); page.wait_for_timeout(150)
        open_guest(GST_NM)
        ok(f"{tag}: 저장 후 게스트는 '개인정보 업데이트하기' + 배지 유지",
           page.inner_text("#pInfoSlot").strip() == "개인정보 업데이트하기"
           and page.eval_on_selector("#mProf", "el=>el.innerText.replace(/\\s+/g,' ').trim()") == "#88 · 180cm · SG")
        page.keyboard.press("Escape"); page.wait_for_timeout(150)

        # 13) 푸터 — 잠금 버튼 제거, 보안 안내 문구는 유지
        page.locator("footer").scroll_into_view_if_needed(); page.wait_for_timeout(200)
        ok(f"{tag}: 푸터 잠금 버튼 없음", page.locator("#lockBtn").count() == 0 and "잠금" not in page.inner_text("footer"))
        ok(f"{tag}: 푸터 보안 안내 문구 유지", "noindex" in page.inner_text("footer") and "데이터 암호화" in page.inner_text("footer"),
           page.inner_text("footer").replace("\n", " ")[-80:])
        page.screenshot(path=f"{OUT}/{tag}_8_footer.png")

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

    # 모바일 유튜브 배지 — 앱 링크 분기 (안드로이드 intent / 아이폰 youtube:// → https fallback)
    UA_AND = ("Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Mobile Safari/537.36")
    UA_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.2 Mobile/15E148 Safari/604.1")
    YT_SUB = "https://www.youtube.com/@stepback_basketball?sub_confirmation=1"
    for tag, ua in [("android", UA_AND), ("ios", UA_IOS)]:
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, user_agent=ua,
                                  device_scale_factor=2, is_mobile=True, has_touch=True)
        for host in ("**/*youtube.com/**", "**band.us/**", "**map.naver.com/**", "**map.kakao.com/**",
                     "**play.google.com/**", "**apps.apple.com/**"):
            ctx.route(host, lambda route: route.fulfill(status=200, content_type="text/html",
                                                        body="<title>stub</title><h1>stub</h1>"))
        page = ctx.new_page()
        errs, pops = [], []
        page.on("pageerror", lambda e, s=errs: s.append(str(e)))
        page.on("popup", lambda pp, s=pops: s.append(pp.url))
        page.goto(URL, wait_until="load")
        page.fill("#code", CODE); page.press("#code", "Enter")
        page.wait_for_selector(".hero h1", timeout=8000); page.wait_for_timeout(400)

        # 구장 길찾기 — 앱 호출 후 웹/스토어 fallback
        page.click("#gymBtn"); page.wait_for_timeout(400)
        ok(f"{tag}: 길찾기 시트 열림(모바일)", not page.locator("#navModal").is_hidden())
        page.click("#navPick [data-nav='kakao']"); page.wait_for_timeout(1500)
        ok(f"{tag}: 카카오맵 — 앱 호출 후 웹 지도 fallback",
           any("map.kakao.com/link/to/" in u for u in pops) and "카카오맵" in page.inner_text("#navNote"),
           f"popup={pops[:1]} note={page.inner_text('#navNote')}")
        pops.clear()
        page.click("#navPick [data-nav='tmap']"); page.wait_for_timeout(1600)
        store_host = "apps.apple.com" if tag == "ios" else "play.google.com"
        ok(f"{tag}: 티맵 — 앱 없음 안내 + 스토어 fallback",
           "티맵 앱이 필요" in page.inner_text("#navNote") and any(store_host in u for u in pops),
           f"popup={pops[:1]} note={page.inner_text('#navNote')}")
        page.keyboard.press("Escape"); page.wait_for_timeout(250)
        ok(f"{tag}: 길찾기 시트 닫힘(모바일)", page.locator("#navModal").is_hidden())

        ok(f"{tag}: 유튜브 배지 — 앱 호출을 위해 기본 이동 가로챔", page.evaluate("""() => {
              const a = document.querySelector('.hero .ytbadge');
              const ev = new MouseEvent('click', {bubbles: true, cancelable: true});
              a.dispatchEvent(ev); return ev.defaultPrevented;
            }""") is True)
        page.click(".hero .ytbadge")
        page.wait_for_timeout(2300)
        landed = page.url if "youtube.com" in page.url else (pops[-1] if pops else "")
        ok(f"{tag}: 앱 미설치/미지원 시 https 구독 페이지로 대체", YT_SUB in landed, f"main={page.url[:60]} popup={pops[-1:]}")

        # 네이버 밴드 배지 — 앱 호출 후 https fallback
        page.goto(URL, wait_until="load")
        page.wait_for_selector(".hero h1", timeout=8000); page.wait_for_timeout(400)
        ok(f"{tag}: BAND 배지 — 앱 호출을 위해 기본 이동 가로챔", page.evaluate("""() => {
              const a = document.querySelector('.hero .bandbadge');
              const ev = new MouseEvent('click', {bubbles: true, cancelable: true});
              a.dispatchEvent(ev); return ev.defaultPrevented;
            }""") is True)
        pops.clear()
        page.click(".hero .bandbadge")
        page.wait_for_timeout(1900)
        band_landed = page.url if "band.us/band/63120390" in page.url else (pops[-1] if pops else "")
        ok(f"{tag}: BAND 앱 미설치/미지원 시 https 바로가기로 대체", "https://band.us/band/63120390" in band_landed,
           f"main={page.url[:60]} popup={pops[-1:]}")
        ok(f"{tag}: JS 에러 0건", len(errs) == 0, "; ".join(errs[:3]))
        ctx.close()

    # 날씨 API 실패 시 — 시트 UI 유지·JS 에러 없음 (앱 링크 테스트는 별도 컨텍스트)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    ctx.route("**api.open-meteo.com/**", lambda route: route.abort())
    page = ctx.new_page()
    wxerrs = []
    page.on("pageerror", lambda e: wxerrs.append(str(e)))
    page.goto(URL, wait_until="load")
    page.fill("#code", CODE); page.press("#code", "Enter")
    page.wait_for_selector(".hero h1", timeout=8000)
    page.click("#gymBtn"); page.wait_for_timeout(1800)
    ok("날씨 실패: 대체 안내 표시", "불러오지 못했습니다" in page.inner_text("#navWx"), page.inner_text("#navWx"))
    ok("날씨 실패: 시트·내비 버튼 정상 유지",
       not page.locator("#navModal").is_hidden() and page.locator("#navPick [data-nav]").count() == 3
       and page.inner_text("#navModal .nvgym .gaddr") == "경기도 시흥시 대야동 500-2")
    page.screenshot(path=f"{OUT}/wx_fail.png")
    ok("날씨 실패: JS 에러 0건", len(wxerrs) == 0, "; ".join(wxerrs[:2]))
    ctx.close()
    browser.close()
if httpd: httpd.shutdown()

fails = [r for r in results if not r[1]]
print("\n=== 결과: %d/%d 통과, 실패 %d ===" % (len(results) - len(fails), len(results), len(fails)))
for f in fails:
    print("  FAIL:", f[0], f[2])
sys.exit(1 if fails else 0)
