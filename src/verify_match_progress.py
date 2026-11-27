# -*- coding: utf-8 -*-
"""경기진행패치 검증 — 매치 프리뷰 등록(짝꿍·팀 구성 연동) → 🏀 경기 진행 기록지 → 사진 저장까지.

    python3 src/verify_match_progress.py                 # 로컬 index.html (390×844 · 1280×800)
    MP_URL=https://youngik-kim.github.io/stepback-basketball/ python3 src/verify_match_progress.py   # 라이브

검사: 프리뷰 등록(직접·짝꿍·팀 구성), 3파전 점수·휴식 횟수 0→1→2→3→1·휴식 순서 정하기·드래그,
      2파전 1~3Q/1~4Q·쉬는 순번·휴식 횟수 없음, 테마·글씨 크기·전체화면·초기화 확인·사진 저장(PNG)·A4 인쇄,
      JS 오류 0건, 평문 이름 0건.
"""
import functools, http.server, io, itertools, json, os, socketserver, sys, threading
from playwright.sync_api import sync_playwright

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('MP_OUT') or os.path.join(SITE, '_verify_mppatch')
os.makedirs(OUT, exist_ok=True)
CODE = io.open(os.path.join(SITE, '.entry-code'), encoding='utf-8').read().strip()
DATA = json.loads(io.open(os.path.join(SITE, 'src', 'data.json'), encoding='utf-8').read())
NAMES = [p['name'] for p in DATA['members']] + [p['name'] for p in DATA['outsiders']]
GUESTS = [g['name'] for g in DATA['guests'] if not g.get('absent')]
POOL = NAMES + GUESTS
ALLNAMES = set(NAMES) | {g['name'] for g in DATA['guests']} | set(DATA['absent'])

# 개인 누적 승률(사이트 personTotals 와 같은 계산: 로스터×팀 성적 합산)
TOT = {}
for w in DATA['weeks']:
    for sh in w['sheets']:
        st = {s['team']: s for s in sh['standings']}
        for team, ns in sh['rosters'].items():
            s = st.get(team, {'w': 0, 'd': 0, 'l': 0})
            g = s['w'] + s.get('d', 0) + s['l']
            for n in ns:
                o = TOT.setdefault(n, {'w': 0, 'g': 0})
                o['w'] += s['w']
                o['g'] += g


def rate(n):
    t = TOT.get(n)
    return (t['w'] / t['g'] * 100) if t and t['g'] else None


def avg_rate(names):
    rs = [rate(n) for n in names if rate(n) is not None]
    return (sum(rs) / len(rs)) if rs else None


URL = os.environ.get('MP_URL')
httpd = None
if not URL:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=SITE)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    URL = 'http://127.0.0.1:%d/' % httpd.server_address[1]
print('target', URL)

results = []


def ok(name, cond, extra=''):
    results.append((name, bool(cond), extra))
    print(('PASS ' if cond else 'FAIL ') + name + ((' — ' + str(extra)) if extra else ''))


def txt(page, sel):
    try:
        return page.inner_text(sel)
    except Exception:
        return ''


def drag(page, from_sel, to_sel, steps=10):
    try:
        page.locator(from_sel).first.scroll_into_view_if_needed()
    except Exception:
        pass
    a = page.locator(from_sel).first.bounding_box()
    b = page.locator(to_sel).first.bounding_box()
    if not a or not b:
        return False
    page.mouse.move(a['x'] + a['width'] / 2, a['y'] + a['height'] / 2)
    page.mouse.down()
    page.mouse.move(a['x'] + a['width'] / 2, a['y'] + a['height'] / 2 + 8, steps=3)
    page.mouse.move(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2, steps=steps)
    page.mouse.up()
    return True


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for tag, w, h in [('m', 390, 844), ('d', 1280, 800)]:
        ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=2 if tag == 'm' else 1,
                                  accept_downloads=True)
        page = ctx.new_page()
        errs = []
        page.on('console', lambda m: errs.append('console.%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errs.append('pageerror: %s' % e))
        page.goto(URL, wait_until='load')
        page.evaluate("localStorage.clear()")
        page.reload(wait_until='load')
        page.wait_for_timeout(300)
        src = page.content()
        ok('%s: 잠금 화면 소스에 평문 이름 0건' % tag, not any(n in src for n in ALLNAMES))
        page.fill('#code', CODE)
        page.click('#go')
        page.wait_for_timeout(1100)
        ok('%s: 입장' % tag, page.locator('#secResult').is_visible())

        # ---- 히어로 3등분 버튼 ----
        hb = page.eval_on_selector_all('.duobtns .pairbtn', '''els => els.map(e => ({
              t: e.innerText.replace(/\\s+/g, ' ').trim(),
              w: Math.round(e.getBoundingClientRect().width),
              top: Math.round(e.getBoundingClientRect().top),
              clip: e.scrollWidth > e.clientWidth + 1
            }))''')
        ok('%s: 히어로 버튼 3개(짝꿍 승률·팀 구성·매치 프리뷰)' % tag,
           len(hb) == 3 and all(k in hb[i]['t'] for i, k in enumerate(['짝꿍 승률', '팀 구성', '매치 프리뷰'])), hb)
        ok('%s: 히어로 3버튼 한 줄 1:1:1' % tag,
           len(hb) == 3 and len({h2['top'] for h2 in hb}) == 1
           and max(h2['w'] for h2 in hb) - min(h2['w'] for h2 in hb) <= 1
           and not any(h2['clip'] for h2 in hb), hb)
        page.screenshot(path='%s/%s_0_hero.png' % (OUT, tag))

        # ---- 등록 버튼 (경기 결과 상단) ----
        btn = page.locator('#mpRegBtn')
        ok('%s: 경기 결과 상단 📝 매치 프리뷰 등록하기 버튼' % tag,
           btn.is_visible() and '매치 프리뷰 등록하기' in btn.inner_text(),
           btn.inner_text().replace('\n', ' '))
        ok('%s: 등록 버튼이 경기 결과 첫 카드보다 위' % tag, page.evaluate("""() => {
              const b = document.querySelector('#mpRegBtn').getBoundingClientRect();
              const r = document.querySelector('#resultCard').getBoundingClientRect();
              return b.top < r.top;
            }"""))

        # ---- 직접 등록 (3파전 · 4Q · 6/6/6) — 히어로 📝 매치 프리뷰 ----
        page.click('#mpHeroBtn')
        page.wait_for_timeout(260)
        ok('%s: 📝 매치 프리뷰 → 등록/편집 + 이력 모달' % tag,
           page.locator('#mpModal').is_visible() and page.locator('#mpType').is_visible()
           and page.locator('#mpHist').count() == 1, page.locator('#mpHist').is_hidden())
        ok('%s: 3파전 규칙 문구(최대 6명)' % tag, '최대 6명' in txt(page, '#mpRule') and '형광' in txt(page, '#mpRule'),
           txt(page, '#mpRule'))
        ok('%s: 기본 3파전·1~4Q' % tag,
           page.get_attribute('#mpType [data-mptype="3"]', 'aria-pressed') == 'true'
           and page.get_attribute('#mpQtr [data-mpq="4"]', 'aria-pressed') == 'true')
        teams3 = [POOL[0:6], POOL[6:12], POOL[12:18]]
        for ti, group in enumerate(teams3):
            page.locator('#mpTeams > .mpteam').nth(ti).click()
            for n in group:
                page.click('#mpPool [data-mppick="%s"]' % n)
            page.wait_for_timeout(60)
        counts = page.eval_on_selector_all('#mpTeams .cnt', 'els => els.map(e => e.textContent)')
        ok('%s: 팀별 인원 6/6/6 표시' % tag, counts == ['6/6명', '6/6명', '6/6명'], counts)
        page.screenshot(path='%s/%s_1_editor.png' % (OUT, tag))
        # 7번째는 막힘
        extra_name = POOL[18]
        page.locator('#mpTeams > .mpteam').nth(0).click()
        page.click('#mpPool [data-mppick="%s"]' % extra_name)
        page.wait_for_timeout(120)
        ok('%s: 3파전 팀당 최대 6명 제한' % tag, '최대 6명' in txt(page, '#mpMsg'), txt(page, '#mpMsg'))
        page.fill('#mpDate', '2026-11-22')
        page.click('#mpSave')
        page.wait_for_timeout(320)
        ok('%s: 등록 완료 → 매치 프리뷰 카드' % tag,
           page.locator('#mpCard').count() == 1 and '3파전' in txt(page, '#mpCard'),
           txt(page, '#mpCard').replace('\n', ' ')[:90])
        card = txt(page, '#mpCard')
        exp = sorted([(avg_rate(g), nm) for g, nm in zip(teams3, ['형광', '블랙', '레드'])], reverse=True)
        top = exp[0][1]
        ok('%s: 카드 예상 1위 = 평균 승률 1위(%s)' % (tag, top),
           ('예상 1위' in card) and (top in card.split('예상 1위')[1][:12]), card.split('★')[0][-20:])
        ok('%s: 카드에 평균 승률 %% 표시' % tag, '%' in card and '명' in card)
        page.screenshot(path='%s/%s_2_card.png' % (OUT, tag))

        # ---- 이력 목록 + 지난 주차 실제 결과 비교 ----
        page.click('#mpHeroBtn')
        page.wait_for_timeout(320)
        ok('%s: 모달에 매치 프리뷰 이력 표시' % tag,
           page.locator('#mpHist').is_visible() and page.locator('#mpHistList .mphrow').count() >= 1,
           page.locator('#mpHistList .mphrow').count())
        page.click('#mpHistList .mphrow summary')
        page.wait_for_timeout(180)
        htxt = page.inner_text('#mpHistList .mphrow')
        ok('%s: 이력에 예상 순위·평균 승률' % tag, '예상 1위' in htxt and '%' in htxt, htxt[:90].replace('\n', ' | '))
        ok('%s: 이력에 실제 결과 비교' % tag, '실제 1위' in htxt and ('✓' in htxt or '✗' in htxt), htxt[:140].replace('\n', ' | '))
        page.screenshot(path='%s/%s_2b_hist.png' % (OUT, tag))
        page.click('#mpModal .x')
        page.wait_for_timeout(200)
        ok('%s: 경기 결과 카드에 🔮 매치 프리뷰 배지' % tag,
           page.locator('.mpwbtn').count() >= 1, page.locator('.mpwbtn').count())
        page.click('.mpwbtn')
        page.wait_for_timeout(320)
        ok('%s: 🔮 배지 → 그 날짜 매치 프리뷰 열기' % tag,
           page.locator('#mpModal').is_visible()
           and page.locator('#mpHistList .mphrow[open][data-hdate="2026-11-22"]').count() == 1)
        page.screenshot(path='%s/%s_2c_weekbadge.png' % (OUT, tag))
        page.click('#mpModal .x')
        page.wait_for_timeout(200)

        # ---- 경기 진행 화면 ----
        page.click('[data-mpgo]')
        page.wait_for_timeout(320)
        ok('%s: 🏀 경기 진행하기 → 진행 화면' % tag, page.locator('#mpScreen').is_visible())
        ok('%s: 진행 화면 제목·부제' % tag, '3파전' in txt(page, '#mpGameTitle') and '4쿼터' in txt(page, '#mpGameSub'),
           txt(page, '#mpGameTitle') + ' | ' + txt(page, '#mpGameSub'))
        ins = page.locator('#mpBody [data-sc]')
        ok('%s: 점수 칸 24개(3경기×4쿼터×2팀)' % tag, ins.count() == 24, ins.count())
        ok('%s: 점수 칸 숫자 직접 입력(inputmode=numeric)' % tag,
           page.get_attribute('#mpBody [data-sc="0:0:a"]', 'inputmode') == 'numeric')
        ok('%s: 인원 추가·삭제 안내 문구' % tag, '인원을 추가·삭제·수정하려면 매치 프리뷰 수정을 이용해 주세요' in txt(page, '#mpBody'))
        # 점수 입력
        for key, val in [('0:0:a', '12'), ('0:0:b', '9'), ('0:1:a', '8'), ('0:1:b', '10'),
                         ('1:0:a', '5'), ('1:0:b', '5'), ('2:0:a', '20'), ('2:0:b', '11')]:
            page.fill('#mpBody [data-sc="%s"]' % key, val)
        page.wait_for_timeout(200)
        tots = page.eval_on_selector_all('#mpBody [data-tot]', 'els => els.map(e => e.textContent.replace(/\\s+/g," ").trim())')
        ok('%s: 경기 합계 자동 계산' % tag, '20 : 19' in tots[0] and '5 : 5' in tots[1] and '20 : 11' in tots[2], tots)
        ok('%s: 승리팀 자동 표시' % tag, '형광 승' in tots[0] and '무승부' in tots[1])
        sumtxt = txt(page, '#mpSum').replace('\n', ' ')
        ok('%s: 팀별 승·무·패 자동 계산(형광 2승)' % tag, '2승 0무 0패' in sumtxt, sumtxt[:70])
        ok('%s: 득실 자동 계산(+10)' % tag, '득실 +10' in sumtxt, sumtxt[:120])
        ok('%s: 우승 배지' % tag, '우승' in sumtxt and page.locator('#mpSum .cr').count() == 1)
        page.screenshot(path='%s/%s_3_screen3.png' % (OUT, tag))

        # ---- 3파전 휴식 횟수 0→1→2→3→1 ----
        rc = page.locator('#mpBody [data-rest]').first
        name0 = rc.get_attribute('data-rest').split('|')[1]
        seq = [rc.inner_text().strip()]
        for _ in range(4):
            page.click('#mpBody [data-rest="0|%s"]' % name0)
            page.wait_for_timeout(80)
            seq.append(page.inner_text('#mpBody [data-rest="0|%s"]' % name0).strip())
        ok('%s: 휴식 횟수 0 → 1 → 2 → 3 → 1 순환' % tag,
           seq[:5] == ['0회', '1회', '2회', '3회', '1회'], seq)
        ok('%s: 휴식 순서·횟수 명단 표기(18명)' % tag,
           page.locator('#mpBody [data-rest]').count() == 18,
           page.locator('#mpBody [data-rest]').count())

        # ---- 휴식 순서 정하기 ----
        page.click('#mpBody [data-prd="0"]')
        page.wait_for_timeout(150)
        ok('%s: 휴식 순서 정하기 모드 안내' % tag, '번호가 붙습니다' in txt(page, '.mprt[data-rt="0"]'),
           txt(page, '.mprt[data-rt="0"]')[:80])
        order = teams3[0][2::-1] + teams3[0][3:]   # 3,2,1,4,5,6 순으로 클릭
        for n in order:
            page.click('#mpBody [data-prow="0|%s"]' % n)
            page.wait_for_timeout(60)
        nos = page.eval_on_selector_all('#mpBody .mprt[data-rt="0"] .mprl li', 'els => els.map(e => [e.querySelector(".nm").textContent, e.querySelector(".no").textContent])')
        ok('%s: 클릭 순서대로 1~6번 부여' % tag,
           [x[0] for x in nos] == order and [x[1] for x in nos] == ['1', '2', '3', '4', '5', '6'],
           nos[:3])
        page.screenshot(path='%s/%s_4_rest.png' % (OUT, tag))

        # ---- 쿼터 드래그 ----
        first_q = page.get_attribute('#mpBody tr[data-qrow]', 'data-qrow')
        if drag(page, '[data-dragq="%s"]' % first_q, 'tr[data-qrow="1"]'):
            page.wait_for_timeout(220)
        qs = page.eval_on_selector_all('#mpBody tr[data-qrow]', 'els => els.map(e => e.getAttribute("data-qrow"))')
        ok('%s: 쿼터 순서 드래그 변경' % tag, qs[0] != first_q, '%s → %s' % (first_q, qs[:4]))

        # ---- 매치업(경기) 순서 클릭·드래그 ----
        g0 = page.eval_on_selector_all('#mpBody thead th[data-gcol]', 'els => els.map(e => e.getAttribute("data-gcol"))')
        page.click('#mpBody [data-gmove="%s:1"]' % g0[0])
        page.wait_for_timeout(160)
        g1 = page.eval_on_selector_all('#mpBody thead th[data-gcol]', 'els => els.map(e => e.getAttribute("data-gcol"))')
        ok('%s: 매치업 순서 클릭(▶) 변경' % tag, g1[0] == g0[1] and g1[1] == g0[0], '%s → %s' % (g0, g1))
        if drag(page, '[data-dragg="%s"]' % g1[2], 'thead th[data-gcol="%s"]' % g1[0]):
            page.wait_for_timeout(220)
        g2 = page.eval_on_selector_all('#mpBody thead th[data-gcol]', 'els => els.map(e => e.getAttribute("data-gcol"))')
        ok('%s: 매치업 순서 드래그 변경' % tag, g2 != g1, '%s → %s' % (g1, g2))

        # ---- 명단 순서 드래그 ----
        before = page.eval_on_selector_all('#mpBody .mprt[data-rt="1"] .mprl li .nm', 'els => els.map(e => e.textContent)')
        if drag(page, '[data-dragp="1|%s"]' % before[0], '.mprt[data-rt="1"] .mprl li:nth-child(3)'):
            page.wait_for_timeout(220)
        after = page.eval_on_selector_all('#mpBody .mprt[data-rt="1"] .mprl li .nm', 'els => els.map(e => e.textContent)')
        ok('%s: 명단 인원 순서 드래그 변경' % tag, after != before, '%s → %s' % (before[:3], after[:3]))

        # ---- 테마 · 글씨 크기 · 전체화면 · 화면꺼짐 방지 ----
        page.click('[data-mpctl="theme"]')
        page.wait_for_timeout(200)
        ok('%s: 🌓 밝은 테마 전환' % tag,
           page.evaluate("document.querySelector('#mpScreen').classList.contains('light')")
           and '어두운 테마' in txt(page, '#mpThemeBtn'))
        page.screenshot(path='%s/%s_5_light.png' % (OUT, tag))
        page.click('[data-mpctl="theme"]')
        page.wait_for_timeout(150)
        ok('%s: 🌓 어두운 테마 복귀' % tag,
           not page.evaluate("document.querySelector('#mpScreen').classList.contains('light')")
           and '밝은 테마' in txt(page, '#mpThemeBtn'))
        base_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprl li .nm')).fontSize)")
        page.click('[data-mpctl="font"]')
        page.wait_for_timeout(160)
        big_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprl li .nm')).fontSize)")
        ok('%s: 🔎 글씨 크기 조절(보통→크게)' % tag, big_fs > base_fs and '크게' in txt(page, '#mpFontBtn'),
           '%s → %s' % (base_fs, big_fs))
        page.click('[data-mpctl="font"]')
        page.wait_for_timeout(120)
        small_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprl li .nm')).fontSize)")
        ok('%s: 🔎 글씨 크기 작게' % tag, small_fs < base_fs and '작게' in txt(page, '#mpFontBtn'),
           '%s → %s' % (base_fs, small_fs))
        page.click('[data-mpctl="font"]')
        page.wait_for_timeout(120)
        page.click('[data-mpctl="full"]')
        page.wait_for_timeout(320)
        ok('%s: ⛶ 전체화면 버튼 동작(요청 또는 오버레이 폴백)' % tag,
           page.get_attribute('#mpFullBtn', 'aria-pressed') == 'true' and '전체화면 종료' in txt(page, '#mpFullBtn'),
           txt(page, '#mpFullBtn'))
        page.click('[data-mpctl="full"]')
        page.wait_for_timeout(220)
        ok('%s: ⛶ 전체화면 해제' % tag,
           page.get_attribute('#mpFullBtn', 'aria-pressed') == 'false' and '전체화면' in txt(page, '#mpFullBtn'))
        ok('%s: 🔆 화면꺼짐 방지 토글(진입 시 자동 ON)' % tag,
           page.get_attribute('#mpWakeBtn', 'aria-pressed') == 'true' and 'ON' in txt(page, '#mpWakeBtn'))

        # ---- 사진 저장(PNG) ----
        try:
            with page.expect_download(timeout=15000) as dl:
                page.click('[data-mpctl="photo"]')
            d = dl.value
            path = '%s/%s_photo_%s' % (OUT, tag, d.suggested_filename)
            d.save_as(path)
            size = os.path.getsize(path)
            sig = io.open(path, 'rb').read(8)
            ok('%s: 📸 사진 저장 PNG 생성' % tag, size > 8000 and sig == b'\x89PNG\r\n\x1a\n',
               '%s · %d bytes' % (d.suggested_filename, size))
        except Exception as ex:
            ok('%s: 📸 사진 저장 PNG 생성' % tag, False, str(ex)[:120])

        # ---- A4 인쇄 ----
        try:
            page.click('[data-mpctl="print"]', timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(250)
        ptxt = txt(page, '#mpPrint')
        ok('%s: 🖨️ A4 인쇄 레이어 생성(고대비 흑백 기록지)' % tag,
           '경기 기록지' in ptxt and '합계' in ptxt and '명단' in ptxt,
           ptxt[:60].replace('\n', ' '))
        page.evaluate("document.body.classList.add('mp-printing')")
        page.emulate_media(media='print')
        page.wait_for_timeout(200)
        shown = page.evaluate("getComputedStyle(document.querySelector('#mpPrint')).display !== 'none'")
        ok('%s: 🖨️ 인쇄 미디어에서 기록지만 표시' % tag, shown,
           page.evaluate("getComputedStyle(document.querySelector('.wrap')).display"))
        page.screenshot(path='%s/%s_6_print.png' % (OUT, tag), full_page=True)
        page.emulate_media(media='screen')
        page.evaluate("document.body.classList.remove('mp-printing')")

        # ---- 초기화 확인 팝업 ----
        page.screenshot(path='%s/%s_7_before_reset.png' % (OUT, tag))
        page.click('[data-mpctl="reset"]')
        page.wait_for_timeout(160)
        ok('%s: 🔄 전체 초기화 확인 팝업 문구' % tag,
           page.locator('#mpConfirm').is_visible()
           and txt(page, '#mpCfMsg').strip() == '초기화 시 기록이 삭제됩니다. 계속 진행하시겠어요?',
           txt(page, '#mpCfMsg'))
        page.screenshot(path='%s/%s_8_reset_confirm.png' % (OUT, tag))
        page.click('#mpCfNo')
        page.wait_for_timeout(120)
        ok('%s: 초기화 취소 시 기록 유지' % tag, page.input_value('#mpBody [data-sc="0:0:a"]') != '')
        page.click('[data-mpctl="reset"]')
        page.wait_for_timeout(140)
        page.click('#mpCfOk')
        page.wait_for_timeout(220)
        empt = page.eval_on_selector_all('#mpBody [data-sc]', 'els => els.filter(e => e.value !== "").length')
        ok('%s: 초기화 확인 → 점수·기록 삭제' % tag, empt == 0 and '미입력' in txt(page, '#mpBody'), empt)

        # ---- 매치 프리뷰 수정하기(진행 화면 안) ----
        page.click('#mpEditBtn')
        page.wait_for_timeout(240)
        ok('%s: 진행 화면 → ✏️ 매치 프리뷰 수정하기' % tag,
           page.locator('#mpModal').is_visible() and '수정' in txt(page, '#mpTitle'))
        page.screenshot(path='%s/%s_9_edit_from_screen.png' % (OUT, tag))

        # ---- 2파전 (5~8명 · 1~3Q/1~4Q) ----
        page.click('#mpType [data-mptype="2"]')
        page.wait_for_timeout(200)
        ok('%s: 2파전 규칙 문구(5~8명·블랙·레드)' % tag,
           '5~8명' in txt(page, '#mpRule') and '블랙' in txt(page, '#mpRule'), txt(page, '#mpRule'))
        page.click('#mpQtr [data-mpq="3"]')
        page.wait_for_timeout(120)
        red = POOL[0:7]
        black = POOL[7:14]
        page.locator('#mpTeams > .mpteam').nth(0).click()
        for n in black:
            page.click('#mpPool [data-mppick="%s"]' % n)
        page.locator('#mpTeams > .mpteam').nth(1).click()
        for n in red:
            page.click('#mpPool [data-mppick="%s"]' % n)
        page.wait_for_timeout(100)
        ok('%s: 2파전 팀당 7명 구성' % tag,
           page.eval_on_selector_all('#mpTeams .cnt', 'els => els.map(e => e.textContent)') == ['7/8명', '7/8명'])
        page.click('#mpSave')
        page.wait_for_timeout(360)
        page.click('#mpClose')
        page.wait_for_timeout(260)
        ok('%s: 2파전 등록 → 카드 갱신' % tag, '2파전' in txt(page, '#mpCard') and '3쿼터' in txt(page, '#mpCard'),
           txt(page, '#mpCard')[:60].replace('\n', ' '))
        page.click('[data-mpgo]')
        page.wait_for_timeout(320)
        ok('%s: 2파전 진행 화면 입력 칸 18개(3경기×3쿼터×2)' % tag,
           page.locator('#mpBody [data-sc]').count() == 18, page.locator('#mpBody [data-sc]').count())
        # 경기(열)별로 쿼터를 따라 읽으면 1·2 → 3·4 → 5·6 → 7·1 순환
        rests = page.eval_on_selector_all('#mpBody [data-cell]',
            '''els => els.map(e => [e.getAttribute('data-cell'), e.querySelector('.mprestl').textContent.replace(/\\s+/g, ' ').trim()])''')
        rmap = dict(rests)
        ok('%s: 2파전 쉬는 순번 자동 표기(1·2 → 3·4 → 5·6 → 7·1)' % tag,
           '1·2' in rmap['0:0'] and '3·4' in rmap['0:1'] and '5·6' in rmap['0:2'] and '7·1' in rmap['1:0'],
           [rmap[k] for k in ['0:0', '0:1', '0:2', '1:0', '1:1']])
        ok('%s: 2파전 휴식 횟수 버튼 없음' % tag, page.locator('#mpBody [data-rest]').count() == 0)
        ok('%s: 2파전 하이라이트 메모 없음' % tag, '하이라이트' not in txt(page, '#mpBody'))
        ok('%s: 2파전 휴식 순서 정하기 제공' % tag, page.locator('#mpBody [data-prd]').count() == 2)
        page.screenshot(path='%s/%s_10_screen2.png' % (OUT, tag))

        # 1~4Q 로 바꾸면 칸 수 증가
        page.click('#mpEditBtn')
        page.wait_for_timeout(240)
        page.click('#mpQtr [data-mpq="4"]')
        page.wait_for_timeout(140)
        page.click('#mpSave')
        page.wait_for_timeout(360)
        ok('%s: 2파전 1~4Q 전환 → 24칸' % tag, page.locator('#mpBody [data-sc]').count() == 24,
           page.locator('#mpBody [data-sc]').count())
        page.click('#mpClose')
        page.wait_for_timeout(240)

        # ---- 짝꿍 승률 계산기 → 매치 프리뷰 등록 ----
        page.click('#pairBtn')
        page.wait_for_timeout(300)
        picks = NAMES[0:5]
        for n in picks:
            page.click('#pChips [data-pick2="%s"]' % n)
        page.wait_for_timeout(200)
        ok('%s: 짝꿍 결과에 📝 매치 프리뷰 등록 버튼' % tag,
           page.locator('#pResult [data-mpfrompair]').count() == 1)
        page.click('#pResult [data-mpfrompair]')
        page.wait_for_timeout(320)
        ok('%s: 짝꿍 선택 인원이 프리뷰 팀에 들어감' % tag,
           page.locator('#mpModal').is_visible()
           and page.locator('#mpTeams .mpteam').nth(0).inner_text().count('\n') >= 5
           and all(n in page.locator('#mpTeams .mpteam').nth(0).inner_text() for n in picks),
           page.locator('#mpTeams .mpteam').nth(0).inner_text().replace('\n', ' ')[:80])
        page.screenshot(path='%s/%s_11_from_pair.png' % (OUT, tag))
        page.click('#mpModal .x')
        page.wait_for_timeout(200)
        page.click('#pairModal .x')
        page.wait_for_timeout(200)

        # ---- 팀 구성 추천 → 매치 프리뷰 등록 ----
        page.click('#teamBtn')
        page.wait_for_timeout(420)
        ok('%s: 팀 구성 결과에 📝 매치 프리뷰 등록 버튼' % tag,
           page.locator('#tResult [data-mpfromteam]').count() == 1)
        page.click('#tResult [data-mpfromteam]')
        page.wait_for_timeout(420)
        ok('%s: 팀 구성 → 매치 프리뷰 카드 즉시 등록' % tag,
           page.locator('#mpCard').count() == 1 and '3파전' in txt(page, '#mpCard'),
           txt(page, '#mpCard')[:50].replace('\n', ' '))
        ok('%s: 등록 카드가 경기 결과 최상단' % tag, page.evaluate("""() => {
              const c = document.querySelector('#mpCard').getBoundingClientRect();
              const r = document.querySelector('#resultCard').getBoundingClientRect();
              return c.top < r.top;
            }"""))
        page.screenshot(path='%s/%s_12_from_team.png' % (OUT, tag))

        # 가로 넘침 없음
        ok('%s: 가로 넘침 없음' % tag, page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),
           page.evaluate('document.documentElement.scrollWidth + "/" + innerWidth'))
        ok('%s: JS 오류 0건' % tag, not errs, ' / '.join(errs[:3]))
        ctx.close()

    # 데스크톱 진행 화면 스크린샷(전체)
    browser.close()

if httpd:
    httpd.shutdown()

fails = [r for r in results if not r[1]]
print('\n%d checks · %d passed · %d failed' % (len(results), len(results) - len(fails), len(fails)))
if fails:
    print('FAILED:')
    for f in fails:
        print(' -', f[0], ('| ' + str(f[2])) if f[2] else '')
    sys.exit(1)
