# -*- coding: utf-8 -*-
"""경기진행패치 검증 — 매치 프리뷰 등록(짝꿍·팀 구성 연동) → 🏀 경기 진행 기록지 → 사진 저장까지.

    python3 src/verify_match_progress.py                 # 로컬 index.html (390×844 · 1280×800)
    MP_URL=https://youngik-kim.github.io/stepback-basketball/ python3 src/verify_match_progress.py   # 라이브

검사: 프리뷰 등록(직접·짝꿍·팀 구성), 3파전 점수·휴식 횟수 0→1→2→3→0·휴식 순서 정하기·드래그,
      2파전 1~3Q/1~4Q·쉬는 순번·휴식 횟수 없음, 테마 3단계(어두운·중간·밝은)·글씨 크기 기본 크게·전체화면·
      초기화 확인·매치 프리뷰 정본 복원·확정 주차 정본 우선·사진 저장(PNG)·A4 인쇄·가로 분할 비율, JS 오류 0건, 평문 이름 0건.
"""
import functools, http.server, io, itertools, json, os, shutil, socketserver, subprocess, sys, threading
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

        # ---- 📋 주요 변경점 기록 ----
        page.click('#chgBtn')
        page.wait_for_timeout(260)
        first = txt(page, '#chgList .cl.top')
        ok('%s: 주요 변경점 최상단 2026-11-27 · 기능 · 경기진행패치' % tag,
           '2026-11-27' in first and '기능' in first and '경기진행패치' in first,
           first[:80].replace('\n', ' '))
        page.click('#chgModal .x')
        page.wait_for_timeout(200)

        # ---- 등록 진입점은 히어로 📝 매치 프리뷰 1개 (경기 결과 위 점선 버튼 제거) ----
        ok('%s: 경기 결과 상단 점선 📝 등록 버튼 제거' % tag,
           page.locator('#mpRegBtn').count() == 0
           and page.locator('#secResult .mpen').count() == 0
           and page.locator('.mpenrow').count() == 0,
           page.locator('#secResult .mpen').count())
        ok('%s: 매치 프리뷰 진입점은 히어로 버튼 하나' % tag,
           page.locator('#mpHeroBtn').count() == 1 and page.locator('[data-mpreg]').count() == 0)

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
        note_txt = page.evaluate("() => document.querySelector('#mpSetNote').textContent")
        ok('%s: 인원 추가·삭제 안내 문구(⚙️ 설정 안내문)' % tag,
           '인원을 추가·삭제·수정하려면 매치 프리뷰 수정을 이용해 주세요' in note_txt, note_txt[-40:])
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
        ok('%s: 휴식 횟수 0 → 1 → 2 → 3 → 0 순환' % tag,
           seq[:5] == ['0회', '1회', '2회', '3회', '0회'], seq)
        ok('%s: 휴식 순서·횟수 명단 표기(18명)' % tag,
           page.locator('#mpBody [data-rest]').count() == 18,
           page.locator('#mpBody [data-rest]').count())

        # ---- 팀 색상 구분 — 매치업 헤더 상단선 · 요약/명단 카드 상단선 · 순위 배지 ----
        tcol = page.evaluate('''() => {
            const th = document.querySelector('#mpBody .mpg thead th.gcol');
            const card = document.querySelector('#mpBody .mpsc');
            const rt = document.querySelector('#mpBody .mpth');
            const bar = getComputedStyle(th, '::before').backgroundImage;
            const dots = [...document.querySelectorAll('#mpBody .mpsc .dot')].map(e => getComputedStyle(e).backgroundColor);
            return { bar: bar, cardCls: card.className, cardBar: getComputedStyle(card).borderTopColor,
                     rtCls: rt.className, rtBar: getComputedStyle(rt).borderTopColor,
                     dots: dots, rk: [...document.querySelectorAll('#mpBody .mpsc .rk')].map(e => e.textContent.trim()) };
          }''')
        ok('%s: 매치업 헤더 팀 색상 상단선(두 팀 2색 분할)' % tag,
           'linear-gradient' in tcol['bar'] and tcol['bar'].count('rgb') >= 2, tcol['bar'][:70])
        ok('%s: 팀 요약 카드·명단 카드 팀 색상 상단선' % tag,
           't-' in tcol['cardCls'] and tcol['cardBar'] not in ('rgba(0, 0, 0, 0)', 'transparent')
           and 't-' in tcol['rtCls'] and tcol['rtBar'] not in ('rgba(0, 0, 0, 0)', 'transparent'),
           '%s / %s' % (tcol['cardBar'], tcol['rtBar']))
        ok('%s: 팀 점 3색 구분·순위 배지' % tag,
           len(set(tcol['dots'])) == 3 and len(tcol['rk']) == 3 and all(x.endswith('위') for x in tcol['rk']),
           '%s / %s' % (tcol['dots'], tcol['rk']))
        page.screenshot(path='%s/%s_3b_teamcol.png' % (OUT, tag))
        hf = page.evaluate('''() => { const e = document.querySelector('#mpBody .mpg .tm');
            const c = document.querySelector('#mpBody .mpsc .h .nm');
            const s = getComputedStyle(e), cs = getComputedStyle(c);
            return { fs: parseFloat(s.fontSize), fw: parseInt(s.fontWeight, 10),
                     cfs: parseFloat(cs.fontSize), cfw: parseInt(cs.fontWeight, 10) }; }''')
        ok('%s: 매치업 헤더·순위 카드 팀명 크게·굵게' % tag,
           hf['fs'] >= 11 and hf['fw'] >= 800 and hf['cfs'] >= 11 and hf['cfw'] >= 800, hf)

        # ---- 휴식 순서 정하기 ----
        page.click('#mpBody [data-prd="0"]')
        page.wait_for_timeout(150)
        ok('%s: 휴식 순서 정하기 모드 안내' % tag, '번호가 붙습니다' in txt(page, '#mpBody .mpassignhint'),
           txt(page, '#mpBody .mpassignhint')[:80])
        order = teams3[0][2::-1] + teams3[0][3:]   # 3,2,1,4,5,6 순으로 클릭
        for n in order:
            page.click('#mpBody [data-prow="0|%s"]' % n)
            page.wait_for_timeout(60)
        nos = page.eval_on_selector_all('#mpBody .mprows[data-rt="0"] .mprow', 'els => els.map(e => [e.querySelector(".pgnm").textContent, (e.querySelector(".mppick") || {textContent: ""}).textContent])')
        ok('%s: 클릭 순서대로 1~6번 부여' % tag, [x[0] for x in nos] == order, nos[:3])
        page.screenshot(path='%s/%s_4_rest.png' % (OUT, tag))

        # ---- 쿼터 순서는 고정(▲▼·드래그 삭제), 쿼터 열 슬림 ----
        ok('%s: 쿼터 ▲▼·드래그 컨트롤 삭제(순서 고정)' % tag,
           page.locator('#mpBody [data-qmove]').count() == 0
           and page.locator('#mpBody [data-dragq]').count() == 0
           and page.locator('#mpBody .qh2').count() == 0, 'qmove/dragq 제거')
        qw = page.evaluate('''() => { const th = document.querySelector('#mpBody tr[data-qrow] th.qh');
            const td = document.querySelector('#mpBody tr[data-qrow] td');
            return { qh: th.getBoundingClientRect().width, cell: td.getBoundingClientRect().width }; }''')
        ok('%s: 쿼터 열 슬림(점수 칸 확보)' % tag, qw['qh'] <= 42 and qw['cell'] > qw['qh'] * 2, qw)
        ok('%s: 쿼터 라벨 1Q~4Q 순서 유지' % tag,
           page.eval_on_selector_all('#mpBody tr[data-qrow] th.qh', 'els => els.map(e => e.textContent.trim())')
           == ['1Q', '2Q', '3Q', '4Q'],
           page.eval_on_selector_all('#mpBody tr[data-qrow] th.qh', 'els => els.map(e => e.textContent.trim())'))
        qs = page.eval_on_selector_all('#mpBody tr[data-qrow]', 'els => els.map(e => e.getAttribute("data-qrow"))')
        ok('%s: 쿼터 행 순서 그대로(0,1,2,3)' % tag, qs == ['0', '1', '2', '3'], qs)

        # ---- 합계행·순위카드 가운데 정렬 ----
        al = page.evaluate('''() => {
            const tot = document.querySelector('#mpBody tr.tot td');
            const card = document.querySelector('#mpBody .mpsc');
            const h = card.querySelector('.h'), rec = card.querySelector('.rec');
            return { tot: getComputedStyle(tot).textAlign, card: getComputedStyle(card).textAlign,
                     hjust: getComputedStyle(h).justifyContent, rec: getComputedStyle(rec).textAlign };
          }''')
        ok('%s: 합계행·팀 순위 카드 가운데 정렬' % tag,
           al['tot'] == 'center' and al['card'] == 'center' and al['hjust'] == 'center', al)

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
        before = page.eval_on_selector_all('#mpBody .mprows[data-rt="1"] .mprow .pgnm', 'els => els.map(e => e.textContent)')
        if drag(page, '[data-dragp="1|%s"]' % before[0], '.mprows[data-rt="1"] .mprow:nth-child(3)'):
            page.wait_for_timeout(220)
        after = page.eval_on_selector_all('#mpBody .mprows[data-rt="1"] .mprow .pgnm', 'els => els.map(e => e.textContent)')
        ok('%s: 명단 인원 순서 드래그 변경' % tag, after != before, '%s → %s' % (before[:3], after[:3]))

        # ---- 상단 바 1줄(제목 · ⚙️ 설정 · ⛶ · ✕) ----
        bar = page.evaluate('''() => { const b = document.querySelector('.mpbar'); return {
              h: Math.round(b.getBoundingClientRect().height),
              btns: Array.from(b.querySelectorAll('button')).map(e => e.id),
              ctrls: document.querySelectorAll('.mpctrls').length }; }''')
        ok('%s: 상단 바 1줄 초컴팩트(제목·설정·전체화면·닫기)' % tag,
           bar['h'] <= 56 and bar['btns'] == ['mpSetBtn', 'mpFullBtn', 'mpClose'] and bar['ctrls'] == 0, bar)

        # ---- ⚙️ 설정 패널 ----
        page.click('#mpSetBtn')
        page.wait_for_timeout(240)
        ok('%s: ⚙️ 설정 패널 열림·옵션 모음' % tag,
           page.locator('#mpSet').is_visible() and page.locator('#mpSet .row').count() >= 4
           and page.locator('#mpSet [data-mpctl="print"]').count() == 1
           and page.locator('#mpSet [data-mpctl="photo"]').count() == 1
           and page.locator('#mpSet [data-mpctl="reset"]').count() == 1
           and page.locator('#mpSetEdit').count() == 1)
        ok('%s: ⚙️ 설정 테마 3단계(어두운·중간·밝은)' % tag,
           page.eval_on_selector_all('#mpSetTheme [data-mptheme]', 'els => els.map(e => e.dataset.mptheme)')
           == ['dark', 'mid', 'light'],
           page.eval_on_selector_all('#mpSetTheme [data-mptheme]', 'els => els.map(e => e.textContent)'))
        ok('%s: ⚙️ 설정 🧩 매치 프리뷰 초기화(서버 정본 복원) 버튼' % tag,
           page.locator('#mpSetRestore').count() == 1
           and '매치 프리뷰 초기화' in txt(page, '#mpSetRestore')
           and '서버 정본 복원' in txt(page, '#mpSetRestore'), txt(page, '#mpSetRestore'))
        page.screenshot(path='%s/%s_4b_settings.png' % (OUT, tag))

        # 기본 글씨가 ‘크게’인지 먼저 확인(아무 설정도 건드리기 전)
        big_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprow .pgnm')).fontSize)")
        ok('%s: 🔎 글씨 크기 기본값 크게(fs-l)' % tag,
           page.evaluate("document.querySelector('#mpScreen').classList.contains('fs-l')")
           and page.get_attribute('[data-mpfont="large"]', 'aria-pressed') == 'true'
           and page.get_attribute('[data-mpfont="normal"]', 'aria-pressed') == 'false', big_fs)

        # ---- 🌓 중간 테마 ----
        page.click('[data-mptheme="mid"]')
        page.wait_for_timeout(220)
        mid = page.evaluate('''() => { const s = document.querySelector('#mpScreen');
              const c = document.querySelector('#mpBody .mpsc');
              return { cls: s.className, bg: getComputedStyle(s).backgroundColor,
                       card: getComputedStyle(c).backgroundColor, tx: getComputedStyle(s).color }; }''')
        ok('%s: 🌓 중간 테마 전환(차분한 슬레이트·순백색 아님)' % tag,
           'mid' in mid['cls'].split() and 'light' not in mid['cls'].split()
           and mid['bg'] == 'rgb(220, 227, 236)' and mid['card'] == 'rgb(237, 241, 246)'
           and mid['tx'] == 'rgb(15, 23, 42)'
           and page.get_attribute('[data-mptheme="mid"]', 'aria-pressed') == 'true', mid)
        page.screenshot(path='%s/%s_5a_mid.png' % (OUT, tag))

        page.click('[data-mptheme="light"]')
        page.wait_for_timeout(220)
        lig = page.evaluate('''() => { const s = document.querySelector('#mpScreen');
              const c = document.querySelector('#mpBody .mpsc');
              return { bg: getComputedStyle(s).backgroundColor, card: getComputedStyle(c).backgroundColor,
                       tx: getComputedStyle(s).color }; }''')
        ok('%s: 🌓 밝은 테마 — 오프화이트(순백 아님)' % tag,
           page.evaluate("document.querySelector('#mpScreen').classList.contains('light')")
           and lig['bg'] == 'rgb(241, 244, 248)' and lig['card'] == 'rgb(249, 250, 251)'
           and page.get_attribute('[data-mptheme="light"]', 'aria-pressed') == 'true', lig)
        page.screenshot(path='%s/%s_5_light.png' % (OUT, tag))
        page.click('[data-mptheme="dark"]')
        page.wait_for_timeout(160)
        ok('%s: 🌓 어두운 테마 복귀' % tag,
           not page.evaluate("document.querySelector('#mpScreen').classList.contains('light')")
           and not page.evaluate("document.querySelector('#mpScreen').classList.contains('mid')")
           and page.get_attribute('[data-mptheme="dark"]', 'aria-pressed') == 'true')

        # ---- 🔎 글씨 크기 — 기본 크게 / 보통 / 작게 ----
        page.click('[data-mpfont="normal"]')
        page.wait_for_timeout(160)
        base_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprow .pgnm')).fontSize)")
        ok('%s: 🔎 글씨 크기 보통 < 기본 크게' % tag, base_fs < big_fs, '%s → %s' % (big_fs, base_fs))
        page.click('[data-mpfont="small"]')
        page.wait_for_timeout(140)
        small_fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#mpBody .mprow .pgnm')).fontSize)")
        ok('%s: 🔎 글씨 크기 작게' % tag, small_fs < base_fs, '%s → %s' % (base_fs, small_fs))
        page.click('[data-mpfont="large"]')
        page.wait_for_timeout(140)
        ok('%s: 🔎 글씨 크게 복귀' % tag,
           page.evaluate("document.querySelector('#mpScreen').classList.contains('fs-l')"))
        ok('%s: 🔆 화면꺼짐 방지 토글(진입 시 자동 ON)' % tag,
           page.get_attribute('#mpSetWake', 'aria-pressed') == 'true' and 'ON' in txt(page, '#mpSetWake')
           and '화면꺼짐 방지' in txt(page, '#mpSetWake'))
        page.click('#mpSetWake')
        page.wait_for_timeout(200)
        ok('%s: 🔆 화면꺼짐 방지 OFF 전환' % tag,
           page.get_attribute('#mpSetWake', 'aria-pressed') == 'false')
        page.click('#mpSetWake')
        page.wait_for_timeout(200)
        page.click('#mpSet .x2')
        page.wait_for_timeout(200)
        ok('%s: ⚙️ 설정 패널 닫힘' % tag, page.locator('#mpSet').is_hidden())
        page.click('#mpFullBtn')
        page.wait_for_timeout(320)
        ok('%s: ⛶ 전체화면 버튼 동작(요청 또는 오버레이 폴백)' % tag,
           page.get_attribute('#mpFullBtn', 'aria-pressed') == 'true'
           and page.get_attribute('#mpFullBtn', 'aria-label') in ('전체화면 종료',))
        page.click('#mpFullBtn')
        page.wait_for_timeout(220)
        ok('%s: ⛶ 전체화면 해제' % tag,
           page.get_attribute('#mpFullBtn', 'aria-pressed') == 'false')

        # ---- 사진 저장(PNG) — 테마 PNG + 잉크절약 흑백 PNG 2장 ----
        page.click('#mpSetBtn')
        page.wait_for_timeout(200)
        dls = []
        page.on('download', lambda d: dls.append(d))
        page.click('#mpSet [data-mpctl="photo"]')
        page.wait_for_timeout(2000)
        ok('%s: 📸 사진 저장 PNG 2장 다운로드(테마 + 잉크절약)' % tag, len(dls) == 2,
           [d.suggested_filename for d in dls])
        if len(dls) == 2:
            files = []
            for d in dls[:2]:
                path = '%s/%s_photo2_%s' % (OUT, tag, d.suggested_filename)
                d.save_as(path)
                files.append((d.suggested_filename, path))
            ok('%s: 📸 파일명 — 스텝백_3파전_경기기록_날짜(+_잉크절약).png' % tag,
               files[0][0].startswith('스텝백_3파전_경기기록_2026-11-22')
               and files[0][0].endswith('.png') and '_잉크절약' not in files[0][0]
               and files[1][0].endswith('_잉크절약.png'),
               [f[0] for f in files])
            ok('%s: 📸 두 파일 모두 유효한 PNG' % tag,
               all(os.path.getsize(f[1]) > 8000
                   and io.open(f[1], 'rb').read(8) == b'\x89PNG\r\n\x1a\n' for f in files),
               [os.path.getsize(f[1]) for f in files])
            try:
                from PIL import Image
                col = Image.open(files[0][1]).convert('RGB')
                ink = Image.open(files[1][1]).convert('RGB')
                col_bg = col.getpixel((5, 5))
                ink_bg = ink.getpixel((5, 5))
                ink_px = ink.getdata()
                whites = sum(1 for px in ink_px if px == (255, 255, 255))
                blacks = sum(1 for px in ink_px if max(px) <= 40)
                ok('%s: 📸 잉크절약 PNG — 배경 흰색·글씨·테두리 검정' % tag,
                   ink_bg == (255, 255, 255) and blacks > 2000
                   and whites > len(list(ink_px)) * 0.4, '%s / 흑%s' % (ink_bg, blacks))
                ok('%s: 📸 테마 PNG — 현재 테마(어두운) 배경 반영' % tag,
                   col_bg[0] < 40 and col_bg[2] < 60, col_bg)
            except Exception as ex:
                ok('%s: 📸 PNG 색상 검사' % tag, False, str(ex)[:100])
        page.wait_for_timeout(200)

        # ---- A4 인쇄 ----
        try:
            page.click('#mpSet [data-mpctl="print"]', timeout=4000)
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
        prc = page.evaluate('''() => {
            const pp = document.querySelector('#mpPrint .pp');
            const th = document.querySelector('#mpPrint th');
            const td = document.querySelector('#mpPrint td');
            return { body: getComputedStyle(document.body).backgroundColor,
                     bg: getComputedStyle(pp).backgroundColor, tx: getComputedStyle(pp).color,
                     thbg: getComputedStyle(th).backgroundColor, thtx: getComputedStyle(th).color,
                     tdb: getComputedStyle(td).borderTopColor, tdtx: getComputedStyle(td).color };
          }''')
        ok('%s: 🖨️ 인쇄 — 배경 순백·글씨·테두리 검정(어두운 테마에서도)' % tag,
           prc['body'] == 'rgb(255, 255, 255)' and prc['bg'] == 'rgb(255, 255, 255)'
           and prc['tx'] == 'rgb(0, 0, 0)' and prc['thbg'] == 'rgb(255, 255, 255)'
           and prc['thtx'] == 'rgb(0, 0, 0)' and prc['tdb'] == 'rgb(0, 0, 0)'
           and prc['tdtx'] == 'rgb(0, 0, 0)', prc)
        page.screenshot(path='%s/%s_6_print.png' % (OUT, tag), full_page=True)
        page.emulate_media(media='screen')
        page.evaluate("document.body.classList.remove('mp-printing')")

        # 중간 테마에서도 인쇄는 순백 배경·검정 글씨
        page.click('[data-mptheme="mid"]')
        page.wait_for_timeout(200)
        try:
            page.click('#mpSet [data-mpctl="print"]', timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(220)
        page.evaluate("document.body.classList.add('mp-printing')")
        page.emulate_media(media='print')
        page.wait_for_timeout(200)
        prm = page.evaluate('''() => {
            const pp = document.querySelector('#mpPrint .pp');
            const th = document.querySelector('#mpPrint th');
            return { body: getComputedStyle(document.body).backgroundColor,
                     bg: getComputedStyle(pp).backgroundColor, tx: getComputedStyle(pp).color,
                     thbg: getComputedStyle(th).backgroundColor,
                     tdb: getComputedStyle(document.querySelector('#mpPrint td')).borderTopColor };
          }''')
        ok('%s: 🖨️ 중간 테마에서도 인쇄 — 순백·검정' % tag,
           prm['body'] == 'rgb(255, 255, 255)' and prm['bg'] == 'rgb(255, 255, 255)'
           and prm['tx'] == 'rgb(0, 0, 0)' and prm['thbg'] == 'rgb(255, 255, 255)'
           and prm['tdb'] == 'rgb(0, 0, 0)', prm)
        page.emulate_media(media='screen')
        page.evaluate("document.body.classList.remove('mp-printing')")
        page.click('[data-mptheme="dark"]')
        page.wait_for_timeout(180)

        # ---- 초기화 확인 팝업 ----
        page.screenshot(path='%s/%s_7_before_reset.png' % (OUT, tag))
        page.click('#mpSet [data-mpctl="reset"]')
        page.wait_for_timeout(180)
        ok('%s: 🔄 전체 초기화 확인 팝업 문구' % tag,
           page.locator('#mpConfirm').is_visible()
           and txt(page, '#mpCfMsg').strip() == '초기화 시 기록이 삭제됩니다. 계속 진행하시겠어요?',
           txt(page, '#mpCfMsg'))
        page.screenshot(path='%s/%s_8_reset_confirm.png' % (OUT, tag))
        page.click('#mpCfNo')
        page.wait_for_timeout(120)
        ok('%s: 초기화 취소 시 기록 유지' % tag, page.input_value('#mpBody [data-sc="0:0:a"]') != '')
        page.click('#mpSet [data-mpctl="reset"]')
        page.wait_for_timeout(140)
        page.click('#mpCfOk')
        page.wait_for_timeout(220)
        empt = page.eval_on_selector_all('#mpBody [data-sc]', 'els => els.filter(e => e.value !== "").length')
        ok('%s: 초기화 확인 → 점수·기록 삭제' % tag, empt == 0 and '미입력' in txt(page, '#mpBody'), empt)

        # ---- 매치 프리뷰 수정하기(설정 패널) ----
        if page.locator('#mpSet').is_hidden():
            page.click('#mpSetBtn')
            page.wait_for_timeout(200)
        page.click('#mpSetEdit')
        page.wait_for_timeout(260)
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
        page.click('#mpSetBtn')
        page.wait_for_timeout(220)
        page.click('#mpSetEdit')
        page.wait_for_timeout(260)
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

    # ---- 가로모드(844×390) — 좌: 점수표+순위 / 우: 명단, 스크롤 없이 한 화면 ----
    ctx = browser.new_context(viewport={'width': 844, 'height': 390}, device_scale_factor=2)
    page = ctx.new_page()
    lerrs = []
    page.on('pageerror', lambda e: lerrs.append(str(e)))
    page.on('console', lambda m: lerrs.append('console: ' + m.text) if m.type == 'error' else None)
    page.goto(URL, wait_until='load')
    page.evaluate("localStorage.clear()")
    page.reload(wait_until='load')
    page.wait_for_timeout(300)
    page.fill('#code', CODE)
    page.click('#go')
    page.wait_for_timeout(1000)
    page.click('#teamBtn')
    page.wait_for_timeout(700)
    page.click('#tResult [data-mpfromteam]')
    page.wait_for_timeout(500)
    page.click('[data-mpgo]')
    page.wait_for_timeout(450)
    geo = page.evaluate('''() => {
          const b = document.querySelector('.mpbody');
          const L = document.querySelector('.mpleft').getBoundingClientRect();
          const R = document.querySelector('.mpright').getBoundingClientRect();
          const S = document.querySelector('#mpScreen');
          const bar = document.querySelector('.mpbar').getBoundingClientRect();
          return {display: getComputedStyle(b).display, leftRight: L.right, rightLeft: R.left,
                  sameTop: Math.abs(L.top - R.top) < 2, screenScroll: S.scrollHeight,
                  bodyScroll: b.scrollHeight, vh: innerHeight, rightBottom: R.bottom,
                  lw: L.width, rw: R.width,
                  cols: getComputedStyle(document.querySelector('.mprshead')).gridTemplateColumns.split(' ').length,
                  barH: Math.round(bar.height)};
        }''')
    ok('l: 가로모드 좌우 분할(왼 점수표·순위 / 오른 명단)', geo['display'] == 'grid'
       and geo['sameTop'] and geo['leftRight'] <= geo['rightLeft'] + 1, geo)
    ok('l: 가로모드 명단 3열(3파전) + 번 열', geo['cols'] == 4, geo['cols'])
    share = geo['lw'] / (geo['lw'] + geo['rw'])
    ok('l: 좌 점수표 : 우 명단 = 58~60% : 40~42%', 0.575 <= share <= 0.605,
       '%.1f%% : %.1f%% (%.1f / %.1f px)' % (share * 100, (1 - share) * 100, geo['lw'], geo['rw']))
    clipped = page.evaluate('''() => [...document.querySelectorAll('#mpBody .mprows')].map(t => {
          const box = t.getBoundingClientRect();
          const last = t.querySelector('.mprow .mpirc');
          return last ? Math.round(last.getBoundingClientRect().right - box.right) : 0; });''')
    ok('l: 오른쪽 명단 3열 잘림 없이 수납', all(c <= 0 for c in clipped) and page.evaluate(
        "[...document.querySelectorAll('#mpBody .mprow .pgnm')].every(e => e.scrollWidth <= e.clientWidth + 1)"), clipped)
    ok('l: 스크롤 없이 한 화면(100dvh) 수납', geo['screenScroll'] <= geo['vh'] + 1
       and geo['rightBottom'] <= geo['vh'] + 1 and geo['barH'] <= 46,
       'scroll=%s vh=%s rightBottom=%s bar=%s' % (geo['screenScroll'], geo['vh'], geo['rightBottom'], geo['barH']))
    rest_visible = page.locator('#mpBody [data-rest]').count()
    ok('l: 가로모드에서도 점수표·명단 모두 보임', page.locator('#mpBody .mpg').is_visible()
       and page.locator('#mpBody .mpth').first.is_visible() and rest_visible >= 15, rest_visible)
    page.screenshot(path='%s/l_landscape.png' % OUT)
    page.click('#mpSetBtn')
    page.wait_for_timeout(260)
    ok('l: 가로모드 ⚙️ 설정 패널', page.locator('#mpSet').is_visible())
    page.screenshot(path='%s/l_landscape_settings.png' % OUT)
    page.click('#mpSet .x2')
    page.wait_for_timeout(180)
    ok('l: JS 오류 0건', not lerrs, ' / '.join(lerrs[:3]))
    ctx.close()

    # ---- 정본(data.json) 매치 프리뷰 연동 — 임시 빌드로 확인 ----
    tmp = os.path.join(OUT, '_canon')
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, 'src'))
    shutil.copy(os.path.join(SITE, 'src', 'template.html'), os.path.join(tmp, 'src', 'template.html'))
    shutil.copy(os.path.join(SITE, 'src', 'build_site.py'), os.path.join(tmp, 'src', 'build_site.py'))
    shutil.copy(os.path.join(SITE, '.entry-code'), os.path.join(tmp, '.entry-code'))
    cdata = json.loads(json.dumps(DATA))
    cnames = POOL[:18]
    cdata['upcomingPreviews'] = [{
        'date': '2026-11-29', 'type': '3파전',
        'teams': [{'team': '레드', 'rate': 48.0, 'players': cnames[0:6]},
                  {'team': '블랙', 'rate': 50.0, 'players': cnames[6:12]},
                  {'team': '형광', 'rate': 52.0, 'players': cnames[12:18]}],
        'expected': {'team': '형광', 'rate': 52.0}, 'written': '2026-11-27', 'note': ''}]
    # 경기 결과가 이미 확정된 주차(2026-11-22)에도 정본 프리뷰를 넣어 우선순위를 검증
    cnames2 = POOL[20:38]
    cdata['weeks'][-1]['preview'] = {
        'type': '3파전',
        'teams': [{'team': '블랙', 'rate': 41.0, 'players': cnames2[0:6]},
                  {'team': '레드', 'rate': 46.5, 'players': cnames2[6:12]},
                  {'team': '형광', 'rate': 55.0, 'players': cnames2[12:18]}],
        'expected': {'team': '형광', 'rate': 55.0}, 'written': '2026-11-22', 'note': ''}
    io.open(os.path.join(tmp, 'src', 'data.json'), 'w', encoding='utf-8').write(json.dumps(cdata, ensure_ascii=False))
    r = subprocess.run([sys.executable, 'src/build_site.py', '--code', CODE], cwd=tmp, capture_output=True, text=True)
    ok('canon: 정본 프리뷰 포함 임시 빌드', r.returncode == 0, (r.stdout or r.stderr)[-120:])
    if r.returncode == 0:
        class Quiet2(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        h2 = functools.partial(Quiet2, directory=tmp)
        srv2 = socketserver.ThreadingTCPServer(('127.0.0.1', 0), h2)
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        U2 = 'http://127.0.0.1:%d/' % srv2.server_address[1]
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2)
        page = ctx.new_page()
        cerrs = []
        page.on('pageerror', lambda e: cerrs.append(str(e)))
        page.goto(U2, wait_until='load')
        page.evaluate("localStorage.clear()")
        page.reload(wait_until='load')
        page.wait_for_timeout(320)
        if page.locator('#code').is_visible():
            page.fill('#code', CODE)
            page.click('#go')
        page.wait_for_timeout(1000)
        ok('canon: 메인 정본 프리뷰 카드에 🏀·✏️ 버튼', page.locator('#previewSlot .pvacts button').count() == 2
           and '경기 진행하기' in page.inner_text('#previewSlot .pvacts')
           and '수정하기' in page.inner_text('#previewSlot .pvacts'),
           page.inner_text('#previewSlot .pvacts').replace('\n', ' '))
        page.screenshot(path='%s/c_1_canoncard.png' % OUT)
        page.click('#mpHeroBtn')
        page.wait_for_timeout(320)
        cnt = page.eval_on_selector_all('#mpTeams .cnt', 'els => els.map(e => e.textContent)')
        ok('canon: 📝 모달이 빈 0명 대신 정본 팀·인원으로 시작', cnt == ['6/6명', '6/6명', '6/6명'],
           '%s | %s' % (cnt, txt(page, '#mpMsg')[:50]))
        page.screenshot(path='%s/c_2_canonmodal.png' % OUT)
        page.click('#mpModal .x')
        page.wait_for_timeout(200)
        page.click('#previewSlot [data-mpcanon="start:2026-11-29"]')
        page.wait_for_timeout(420)
        ok('canon: 정본 카드 🏀 → 경기 진행 화면', page.locator('#mpScreen').is_visible()
           and page.locator('#mpBody [data-sc]').count() == 24
           and page.locator('#mpBody [data-rest]').count() == 18,
           page.locator('#mpBody [data-sc]').count())
        page.screenshot(path='%s/c_3_canonscreen.png' % OUT)
        page.click('#mpClose')
        page.wait_for_timeout(250)
        ok('canon: 진행 후 메인 카드도 등록 상태', page.locator('#mpCard').count() == 1
           and page.locator('#mpCard [data-mpgo]').count() == 1)

        # ---- 확정된 주차 — 기기 등록분보다 서버 정본 프리뷰 우선 ----
        page.evaluate("""() => {
          const c = { date: '2026-11-22', type: '3파전', pv: DATA.weeks[DATA.weeks.length - 1].preview };
          const p = mpFromCanonical(c);
          const a = p.teams[0].players, b = p.teams[1].players;
          p.teams[0].players = b; p.teams[1].players = a;   /* 기기에 다른 구성이 임시 저장된 상황 */
          localStorage.setItem('stepback-mpgame-v1', JSON.stringify({
            previews: [p], activeDate: '2026-11-22', theme: 'dark', font: 'large' }));
        }""")
        page.reload(wait_until='load')
        page.wait_for_timeout(320)
        if page.locator('#code').is_visible():
            page.fill('#code', CODE)
            page.click('#go')
        page.wait_for_timeout(1000)
        can22 = page.evaluate("""() => DATA.weeks[DATA.weeks.length - 1].preview.teams
              .map(t => t.team + ':' + t.players.join(','))""")
        cur22 = page.evaluate("""() => (MP.preview ? MP.preview.teams
              .map(t => t.name + ':' + t.players.map(x => x.name).join(',')) : null)""")
        ok('canon: 확정 주차(2026-11-22) 경기 진행 초기값 = 서버 정본', cur22 == can22,
           '%s / %s' % (str(cur22)[:60], str(can22)[:60]))
        saved22 = page.evaluate("""() => { const o = JSON.parse(localStorage.getItem('stepback-mpgame-v1') || '{}');
              const p = (o.previews || []).filter(x => x.date === '2026-11-22')[0];
              return p ? p.teams.map(t => t.name + ':' + t.players.map(x => x.name).join(',')) : null; }""")
        ok('canon: 기기에 남은 그 날짜 프리뷰도 정본으로 정리', saved22 == can22, str(saved22)[:60])
        hidden_badge = page.locator('.mpwbtn').count()
        page.click('#mpHeroBtn')
        page.wait_for_timeout(320)
        row22 = page.evaluate("""() => { const r = document.querySelector('#mpHistList .mphrow[data-hdate="2026-11-22"]');
              if (!r) return null;
              return { tag: ((r.querySelector('.tag.site') || {}).textContent || '').trim(),
                       loc: !!r.querySelector('.tag.loc'),
                       btn: r.querySelectorAll('.acts button').length,
                       txt: r.innerText.replace(/\\s+/g, ' ').trim().slice(0, 80) }; }""")
        ok('canon: 이력 모달 — 확정 주차는 정본 프리뷰(내 기록 아님)',
           bool(row22) and row22['tag'] == '정본' and not row22['loc'] and row22['btn'] == 0, row22)
        page.screenshot(path='%s/c_4_hist_canon.png' % OUT)
        page.click('#mpModal .x')
        page.wait_for_timeout(200)
        ok('canon: 주간 결과 🔮 배지 표시', hidden_badge >= 1, hidden_badge)
        page.click('.mpwbtn')
        page.wait_for_timeout(320)
        opened = page.evaluate("""() => { const r = document.querySelector('#mpHistList .mphrow[open]');
              return r ? { d: r.dataset.hdate, site: !!r.querySelector('.tag.site') } : null; }""")
        ok('canon: 🔮 배지가 연 행 = 2026-11-22 정본', bool(opened) and opened['d'] == '2026-11-22'
           and opened['site'], opened)
        page.screenshot(path='%s/c_5_weekbadge.png' % OUT)
        page.click('#mpModal .x')
        page.wait_for_timeout(200)

        # ---- 🧩 매치 프리뷰 초기화 (서버 정본 복원) ----
        page.evaluate("""() => {
          const c = mpFindCanonical('2026-11-29');
          const p = mpFromCanonical(c);
          const a = p.teams[0].players, b = p.teams[1].players;
          p.teams[0].players = b; p.teams[1].players = a;
          localStorage.setItem('stepback-mpgame-v1', JSON.stringify({
            previews: [p], activeDate: '2026-11-29', theme: 'dark', font: 'large' }));
        }""")
        page.reload(wait_until='load')
        page.wait_for_timeout(320)
        if page.locator('#code').is_visible():
            page.fill('#code', CODE)
            page.click('#go')
        page.wait_for_timeout(1000)
        page.click('#mpCard [data-mpgo]')
        page.wait_for_timeout(420)
        page.click('#mpSetBtn')
        page.wait_for_timeout(240)
        page.click('#mpSetRestore')
        page.wait_for_timeout(220)
        ok('restore: 확인 팝업 문구', page.locator('#mpConfirm').is_visible()
           and txt(page, '#mpCfMsg').strip() == '기기에 임시 저장된 매치 프리뷰를 지우고 서버 정본 기준으로 되돌릴까요?',
           txt(page, '#mpCfMsg'))
        page.screenshot(path='%s/c_6_restore_confirm.png' % OUT)
        page.click('#mpCfOk')
        page.wait_for_timeout(320)
        gone = page.evaluate("""() => { const o = JSON.parse(localStorage.getItem('stepback-mpgame-v1') || '{}');
              return (o.previews || []).filter(x => x.date === '2026-11-29').length; }""")
        up29 = page.evaluate("""() => DATA.upcomingPreviews[0].teams
              .map(t => t.team + ':' + t.players.join(','))""")
        now29 = page.evaluate("""() => (MP.preview ? MP.preview.teams
              .map(t => t.name + ':' + t.players.map(x => x.name).join(',')) : null)""")
        ok('restore: 기기 임시 프리뷰 삭제 + 정본 기준 재구성', gone == 0 and now29 == up29,
           '%s건 · %s' % (gone, str(now29)[:50]))
        roster29 = page.evaluate("""() => [...document.querySelectorAll('#mpBody .mprows')]
              .map(u => u.querySelectorAll('.mprow').length)""")
        ok('restore: 정본 팀·인원으로 즉시 재렌더링(6/6/6)', roster29 == [6, 6, 6], roster29)
        page.screenshot(path='%s/c_7_restored.png' % OUT)

        # 정본 프리뷰가 없는 날짜 → 빈 프리뷰/기본 화면
        page.evaluate("""() => {
          const c = mpFindCanonical('2026-11-29');
          const p = mpFromCanonical(c); p.date = '2026-12-13';
          localStorage.setItem('stepback-mpgame-v1', JSON.stringify({
            previews: [p], activeDate: '2026-12-13', theme: 'dark', font: 'large' }));
        }""")
        page.reload(wait_until='load')
        page.wait_for_timeout(320)
        if page.locator('#code').is_visible():
            page.fill('#code', CODE)
            page.click('#go')
        page.wait_for_timeout(1000)
        page.click('#mpCard [data-mpgo]')
        page.wait_for_timeout(420)
        page.click('#mpSetBtn')
        page.wait_for_timeout(240)
        page.click('#mpSetRestore')
        page.wait_for_timeout(200)
        page.click('#mpCfOk')
        page.wait_for_timeout(320)
        ok('restore: 정본 프리뷰 없는 날짜 → 완전 빈칸(0명) 프리뷰',
           page.evaluate('() => !!MP.preview && MP.preview.teams.every(t => t.players.length === 0)')
           and page.evaluate('() => MP.previews.length === 0')
           and page.locator('#mpScreen').is_visible()
           and page.locator('#mpBody [data-sc]').count() == 24
           and page.locator('#mpBody [data-rest]').count() == 0,
           'teams=%s previews=%s' % (
               page.evaluate('() => (MP.preview ? MP.preview.teams.map(t => t.players.length) : null)'),
               page.evaluate('() => MP.previews.length')))

        # ---- 📝 등록·편집 모달 하단 — 🧩 정본 초기화 · 🏀 경기 진행하기 ----
        page.click('#mpClose')
        page.wait_for_timeout(220)
        page.click('#mpHeroBtn')
        page.wait_for_timeout(300)
        ok('editor: 하단 🧩 매치 프리뷰 초기화(서버 정본) 버튼',
           page.locator('#mpEdRestore').count() == 1
           and '매치 프리뷰 초기화' in txt(page, '#mpEdRestore'), txt(page, '#mpEdRestore'))
        ok('editor: 하단 🏀 경기 진행하기 버튼',
           page.locator('#mpEdStart').count() == 1 and '경기 진행하기' in txt(page, '#mpEdStart'),
           txt(page, '#mpEdStart'))
        # 안내 문구 — 등록/취소 버튼 바로 위
        n2 = page.evaluate('''() => {
            const n = document.querySelector('#mpModal .mpnote2');
            const f = document.querySelector('#mpModal .mpfoot');
            if (!n || !f) return null;
            return { txt: n.innerText.replace(/\\s+/g, ' ').trim(),
                     above: n.getBoundingClientRect().bottom <= f.getBoundingClientRect().top + 1,
                     visible: getComputedStyle(n).display !== 'none' };
          }''')
        ok('editor: 등록 버튼 바로 위 기기 저장 안내 문구',
           bool(n2) and n2['above'] and n2['visible']
           and '현재 기기(브라우저)' in n2['txt']
           and '서버나 다른 팀원 화면에는 반영되지 않습니다' in n2['txt'], n2)
        # 정본이 있는 2026-11-29 → 정본 인원으로 복원
        page.fill('#mpDate', '2026-11-29')
        page.evaluate("""() => { const p = mpFromCanonical(mpFindCanonical('2026-11-29'));
              const a = p.teams[0].players, b = p.teams[1].players;
              p.teams[0].players = b; p.teams[1].players = a;
              MP.previews = MP.previews.filter(x => x.date !== '2026-11-29').concat([p]);
              MP.preview = p; mpSave(); mpOpenEditor(p); }""")
        page.wait_for_timeout(260)
        page.click('#mpEdRestore')
        page.wait_for_timeout(220)
        ok('editor: 초기화 확인 팝업 문구', page.locator('#mpEdConfirm').is_visible()
           and txt(page, '#mpEdCfMsg').strip() == '기기에 임시 저장된 매치 프리뷰를 지우고 서버 정본 기준으로 되돌릴까요?',
           txt(page, '#mpEdCfMsg'))
        page.screenshot(path='%s/c_8_editor_confirm.png' % OUT)
        page.click('#mpEdCfOk')
        page.wait_for_timeout(320)
        ed_cnt = page.eval_on_selector_all('#mpTeams .cnt', 'els => els.map(e => e.textContent)')
        up29b = page.evaluate("""() => mpFindCanonical('2026-11-29').pv.teams.map(t => t.team + ':' + t.players.join(','))""")
        ed_teams = page.evaluate("""() => MPED.teams.map(t => t.name + ':' + t.players.map(x => x.name).join(','))""")
        gone29 = page.evaluate("""() => { const o = JSON.parse(localStorage.getItem('stepback-mpgame-v1') || '{}');
              return (o.previews || []).filter(x => x.date === '2026-11-29').length; }""")
        ok('editor: 기기 임시 저장 삭제 + 정본 인원으로 복원',
           gone29 == 0 and ed_teams == up29b and ed_cnt == ['6/6명', '6/6명', '6/6명'],
           '%s건 · %s · %s' % (gone29, ed_cnt, str(ed_teams)[:50]))
        page.screenshot(path='%s/c_9_editor_restored.png' % OUT)
        # 정본이 없는 날짜 → 0명 빈칸
        page.fill('#mpDate', '2026-12-13')
        page.click('#mpEdRestore')
        page.wait_for_timeout(200)
        page.click('#mpEdCfOk')
        page.wait_for_timeout(300)
        ed_cnt0 = page.eval_on_selector_all('#mpTeams .cnt', 'els => els.map(e => e.textContent)')
        ok('editor: 정본 없는 날짜 → 0명 빈칸 초기화', ed_cnt0 == ['0/6명', '0/6명', '0/6명']
           and page.evaluate('() => MPED.teams.every(t => t.players.length === 0)')
           and page.evaluate('() => MP.previews.length === 0'), ed_cnt0)
        page.screenshot(path='%s/c_10_editor_blank.png' % OUT)
        # 🏀 경기 진행하기 — 인원 미달이면 안내 후 중지
        page.click('#mpEdStart')
        page.wait_for_timeout(260)
        ok('editor: 🏀 인원 미달이면 안내하고 중지', page.locator('#mpModal').is_visible()
           and page.locator('#mpScreen').is_hidden() and '선수' in txt(page, '#mpMsg'), txt(page, '#mpMsg'))
        page.fill('#mpDate', '2026-11-29')
        page.click('#mpEdRestore')
        page.wait_for_timeout(200)
        page.click('#mpEdCfOk')
        page.wait_for_timeout(300)
        page.click('#mpEdStart')
        page.wait_for_timeout(420)
        ok('editor: 🏀 유효하면 저장 후 경기 진행 화면으로', page.locator('#mpScreen').is_visible()
           and page.locator('#mpModal').is_hidden()
           and page.locator('#mpBody [data-sc]').count() == 24
           and page.locator('#mpBody [data-rest]').count() == 18,
           '%s / %s' % (page.locator('#mpBody [data-sc]').count(), page.locator('#mpBody [data-rest]').count()))
        page.screenshot(path='%s/c_11_editor_start.png' % OUT)
        ok('canon: JS 오류 0건', not cerrs, ' / '.join(cerrs[:3]))
        ctx.close()
        srv2.shutdown()

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
