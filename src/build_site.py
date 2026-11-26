# -*- coding: utf-8 -*-
"""스텝백 사이트 빌드 — data.json 을 입장 코드로 암호화해 index.html + robots.txt 를 만든다.

사용:
    python3 src/build_data.py                    # 기록지 마크다운 -> src/data.json (평문)
    python3 src/build_site.py                    # .entry-code(또는 --code) 로 암호화 빌드
    python3 src/build_site.py --code 1234        # 코드 직접 지정
    STEPBACK_ENTRY_CODE=1234 python3 src/build_site.py

배포물: index.html, robots.txt, .nojekyll
절대 올리면 안 되는 파일: src/data.json(평문 명단), .entry-code(입장 코드)
"""
import argparse, base64, hashlib, io, json, os, secrets, sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITER = 200000
CODE_FILE = os.path.join(SITE, ".entry-code")

b64 = lambda b: base64.b64encode(b).decode("ascii")


def read(p):
    return io.open(p, encoding="utf-8").read()


def w(p, s):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


def get_code(arg):
    code = (arg or os.environ.get("STEPBACK_ENTRY_CODE") or "").strip()
    if not code and os.path.exists(CODE_FILE):
        code = read(CODE_FILE).strip()
    if not code:
        sys.exit("입장 코드가 없습니다. site/.entry-code 파일을 만들거나 --code 로 지정하세요.")
    return code


def encrypt(payload: dict, code: str) -> dict:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ITER, dklen=32)
    ct = AESGCM(key).encrypt(iv, raw, None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "cipher": "AES-GCM",
            "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="입장 코드 (미지정 시 STEPBACK_ENTRY_CODE 또는 .entry-code)")
    args = ap.parse_args()

    data_path = os.path.join(SITE, "src", "data.json")
    if not os.path.exists(data_path):
        sys.exit("src/data.json 이 없습니다. 먼저 python3 src/build_data.py 를 실행하세요.")
    data = json.loads(read(data_path))
    code = get_code(args.code)

    enc = encrypt(data, code)
    tpl = read(os.path.join(SITE, "src", "template.html"))
    if "/*__ENC__*/" not in tpl:
        sys.exit("template.html 에 /*__ENC__*/ 자리표시자가 없습니다.")
    out = tpl.replace("/*__ENC__*/", json.dumps(enc, separators=(",", ":")))
    if "/*__ENC__*/" in out:
        sys.exit("암호문 주입 실패")

    # --- 누출 검사: HTML 소스에 평문 이름·입장 코드가 없어야 한다
    names = set()
    for p in data["members"] + data["outsiders"] + data["guests"] + data["roster"]:
        names.add(p["name"])
    names.update(data["absent"])
    leaks = sorted(n for n in names if n and n in out)
    problems = []
    if leaks:
        problems.append("평문 이름 노출: " + ", ".join(leaks))
    if code in out:
        problems.append("입장 코드가 소스에 그대로 있음")
    if problems:
        sys.exit("빌드 중단 — " + " / ".join(problems))

    w(os.path.join(SITE, "index.html"), out)
    w(os.path.join(SITE, "robots.txt"), "User-agent: *\nDisallow: /\n")
    w(os.path.join(SITE, ".nojekyll"), "")

    sha = hashlib.sha256(out.encode("utf-8")).hexdigest()
    print(f"index.html {len(out.encode('utf-8')):,} bytes")
    print(f"암호문 {len(enc['ct']):,} chars · PBKDF2-SHA256 {ITER:,}회 · AES-256-GCM · salt/iv 새로 생성")
    print(f"평문 이름 검사: 통과 ({len(names)}명 모두 미노출)")
    print(f"robots.txt: User-agent: * / Disallow: /")
    print(f"sha256 {sha[:16]}…")
    print("배포: index.html · robots.txt · .nojekyll 만 (src/data.json · .entry-code 는 제외)")


if __name__ == "__main__":
    main()
