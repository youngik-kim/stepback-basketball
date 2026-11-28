# -*- coding: utf-8 -*-
"""경기 진행 화면·매치 프리뷰 카드 — 리버스(reverse-basketball-site)와 픽셀 단위 비교.

※ 2026-11-28 매치업 머리글 개편(◀▶ 줄 → ⇄ · 쿼터 ↻ · 출석 표시) 이후로는
   **머리글 관련 상자만 의도적으로 다릅니다.** 그 항목은 비교에서 빼고 봅니다.

두 사이트를 같은 뷰포트·같은 조건(3파전 4쿼터)으로 열어 주요 상자의 크기를 재고,
차이가 0.5px 를 넘으면 실패로 보고합니다. 나란히 붙인 캡처도 함께 저장합니다.

    REVERSE_DIR=../reverse-basketball-site REVERSE_CODE=**** python3 src/verify_pgmatch.py
    # 리버스 입장 코드가 필요합니다(암호화 페이지). 없으면 건너뜁니다.

환경변수
    REVERSE_DIR   리버스 저장소 경로 (기본 ../reverse-basketball-site)
    REVERSE_CODE  리버스 입장 코드
    PG_OUT        캡처 폴더 (기본 _verify_pgmatch)
    PG_VIEWPORTS  '844x390,915x412'
"""
import functools, http.server, json, os, socketserver, sys, threading

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sys.exit('playwright 가 필요합니다.')

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('PG_OUT') or os.path.join(SITE, '_verify_pgmatch')
REV_DIR = os.environ.get('REVERSE_DIR') or os.path.join(os.path.dirname(SITE), 'reverse-basketball-site')
REV_CODE = os.environ.get('REVERSE_CODE') or ''
CODE = open(os.path.join(SITE, '.entry-code'), encoding='utf-8').read().strip()
VPS = []
for part in (os.environ.get('PG_VIEWPORTS') or '844x390,915x412').split(','):
    w, h = part.lower().split('x')
    VPS.append({'width': int(w), 'height': int(h)})
os.makedirs(OUT, exist_ok=True)

TOL = 0.5   # px


def serve(d):
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = socketserver.ThreadingTCPServer(('127.0.0.1', 0), functools.partial(Q, directory=d))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return 'http://127.0.0.1:%d/' % srv.server_address[1]


MEASURE = """(sel) => {
  const R = el => { if (!el) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.width * 10) / 10, Math.round(b.height * 10) / 10]; };
  const q = s => document.querySelector(sel + ' ' + s);
  const qa = s => [...document.querySelectorAll(sel + ' ' + s)];
  const th = q('.pgth'), row = q('.pgrow');
  return {
    '상단 바': R(q('.pgbar')),
    '제목': R(q('.pgt')),
    '본문': R(q('.pgbody')),
    '좌 점수표 열': R(qa('.pgcol')[0]),
    '우 명단 열': R(qa('.pgcol')[1]),
    '점수표': R(q('.pgtbl')),
    '점수 칸': R(q('.pgcell')),
    '점수 입력': R(q('.sci')),
    '콜론': R(q('.scc')),
    '매치업 헤더': R(q('.pgtbl th.mh')),
    '팀 배지': R(q('.pgtbl .tm')),
    '명단 머리': R(th),
    '명단 머리 점': th ? R(th.querySelector('.dot')) : null,
    '명단 행': R(row),
    '명단 이름': R(q('.pgnm')),
    '0회 버튼': R(q('.pgrc')),
    '팀 순위 카드': R(qa('.pgs')[0]),
    '명단 표': R(q('.pgrosters')),
  };
}"""


def prep(page, url, gate, go, code, local):
    page.goto(url, wait_until='load')
    page.evaluate('localStorage.clear()')
    page.reload(wait_until='load')
    page.wait_for_timeout(400)
    page.fill(gate, code)
    page.click(go)
    page.wait_for_timeout(1500)
    if local:
        page.evaluate("""() => { const pool = DATA.members.map(m => m.name);
          const p = mpNew('3', 4); p.date = '2026-11-29';
          p.teams.forEach((t, i) => { t.players = pool.slice(i * 5, i * 5 + 5).map(n => ({ name: n, kind: 'member' })); });
          mpNormalize(p); mpUpsert(p); mpPaintHome(); }""")
        page.wait_for_timeout(300)


def open_board(page, sel):
    page.click(sel)
    page.wait_for_timeout(900)
    # 두 사이트 모두 4쿼터로 맞춥니다
    if page.locator('#mpSetBtn').count():
        page.click('#mpSetBtn'); page.wait_for_timeout(300)
        page.click('[data-mpq2="4"]'); page.wait_for_timeout(300)
        page.click('.mpset .x2'); page.wait_for_timeout(500)
    else:
        page.click('[data-pg="set"]'); page.wait_for_timeout(300)
        page.click('[data-pgq="4"]'); page.wait_for_timeout(300)
        page.click('.pgsetp .pgx'); page.wait_for_timeout(500)


def label(img, text, h=52, font=None):
    w = img.width
    out = Image.new('RGB', (w, h + img.height), (255, 255, 255))
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, w, h], fill=(248, 248, 250))
    d.text((16, 12), text, fill=(25, 25, 30), font=font)
    out.paste(img, (0, h))
    return out


def main():
    if not os.path.isdir(REV_DIR):
        print('건너뜀: 리버스 저장소가 없습니다 (%s)' % REV_DIR)
        return 0
    if not REV_CODE:
        print('건너뜀: REVERSE_CODE(리버스 입장 코드)가 없습니다.')
        return 0
    font = None
    if Image:
        for f in ('/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf',):
            if os.path.exists(f):
                font = ImageFont.truetype(f, 28)
    fails = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for vp in VPS:
            res = {}
            for name in ('reverse', 'stepback'):
                url = serve(REV_DIR if name == 'reverse' else SITE)
                ctx = b.new_context(viewport=vp, device_scale_factor=2)
                page = ctx.new_page()
                errs = []
                page.on('pageerror', lambda e: errs.append(str(e)))
                if name == 'reverse':
                    prep(page, url, '#gateCode', '#gateBtn', REV_CODE, False)
                    open_board(page, '#resultCard [data-mp-go]')
                else:
                    prep(page, url, '#code', '#go', CODE, True)
                    open_board(page, '[data-mpgo="1"]')
                res[name] = page.evaluate(MEASURE, '#pg' if name == 'reverse' else '#mpScreen')
                res[name]['JS 오류'] = len(errs)
                page.screenshot(path='%s/%s_%dx%d.png' % (OUT, name, vp['width'], vp['height']))
                ctx.close()
            print('\n== %dx%d ==' % (vp['width'], vp['height']))
            for k in res['reverse']:
                a, c = res['reverse'][k], res['stepback'][k]
                if k == 'JS 오류':
                    ok = c == 0
                else:
                    ok = a is not None and c is not None and max(abs(a[0] - c[0]), abs(a[1] - c[1])) <= TOL
                if not ok:
                    fails += 1
                print('%s %-12s 리버스 %-16s 스텝백 %-16s' % ('OK  ' if ok else 'FAIL', k, a, c))
            if Image:
                a = Image.open('%s/reverse_%dx%d.png' % (OUT, vp['width'], vp['height']))
                c = Image.open('%s/stepback_%dx%d.png' % (OUT, vp['width'], vp['height']))
                i1 = label(a, '리버스 · 경기 진행', font=font)
                i2 = label(c, '스텝백 · 경기 진행', font=font)
                m = Image.new('RGB', (i1.width, i1.height + i2.height + 8), (226, 228, 232))
                m.paste(i1, (0, 0)); m.paste(i2, (0, i1.height + 8))
                m.save('%s/compare_%dx%d.png' % (OUT, vp['width'], vp['height']))
        b.close()
    print('\n=== 결과: %d개 항목 불일치 (허용 %0.1fpx) ===' % (fails, TOL))
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
