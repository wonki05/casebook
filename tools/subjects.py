"""과목(subject)·법률신문 분야(annual field) 정의 — 표준판례 페이지·목차 접두어·PDF 폴더명·주요판례 분야 탭의 단일 출처.

add_cases.py · pdf_standard_cases.py · annual_cases.py · build_data.py 가 모두 여기서 읽는다.
과목을 추가할 때는 이 목록에 한 줄을 넣고, data/toc.json 에 같은 id 의 목차 트리를 만들고,
src/design-d.html 의 MAXIMS / PAGE_DESC 에 'std-<id>' 항목을 더하면 된다(나머지는 자동).
standard 가 False 인 과목(지식재산권법)은 표준판례 페이지·목차 없이 법률신문 주요판례 등에서만 쓰인다.
"""
import re

SUBJECTS = [
    # id              화면 라벨          toc id 접두어   data/standard-cases/ 아래 폴더·PDF 이름에 쓰는 한글 과목명   표준판례 페이지
    {"id": "constitution",   "label": "헌법",         "tocPrefix": "hb",  "folder": "헌법",   "standard": True},
    {"id": "administrative", "label": "행정법",       "tocPrefix": "hj",  "folder": "행정법", "standard": True},
    {"id": "civil",          "label": "민법",         "tocPrefix": "mb",  "folder": "민법",   "standard": True},
    {"id": "criminal",       "label": "형법",         "tocPrefix": "hb2", "folder": "형법",   "standard": True},
    {"id": "commercial",     "label": "상법",         "tocPrefix": "sb",  "folder": "상법",   "standard": True},
    {"id": "ip",             "label": "지식재산권법", "tocPrefix": "",    "folder": "",       "standard": False},
]
SUBJECT_IDS = [s["id"] for s in SUBJECTS]                     # 등록부에 쓸 수 있는 모든 과목
STANDARD_SUBJECTS = [s for s in SUBJECTS if s["standard"]]    # 표준판례 페이지(std-<id>)·목차가 있는 과목
STANDARD_IDS = [s["id"] for s in STANDARD_SUBJECTS]
BY_ID = {s["id"]: s for s in SUBJECTS}

# 법률신문 「분야별 중요판례분석」 페이지의 분야 — 화면의 분야 구분·필터 순서 = 이 목록 순서.
# label 은 분야 이름, sub 는 그 옆의 작은 보라색 글씨. 기사 제목의 연재 순번("(3)" 등)은 화면에 쓰지 않는다.
# keys 는 기사 제목에서 분야를 추정할 때 쓰는 낱말(공백·괄호·가운뎃점을 지운 제목에 들어 있는지 본다: '형법(총칙)' → '형법총칙').
ANNUAL_FIELDS = [
    {"id": "constitution",     "subject": "constitution",   "label": "헌법",         "sub": "",                   "keys": ["헌법"]},
    {"id": "administrative",   "subject": "administrative", "label": "행정법",       "sub": "",                   "keys": ["행정법"]},
    {"id": "civil",            "subject": "civil",          "label": "민법",         "sub": "총칙·물권법·채권법", "keys": ["민법", "물권법", "채권법"]},
    {"id": "family",           "subject": "civil",          "label": "민법",         "sub": "가족법",             "keys": ["가족법", "친족", "상속법"]},
    {"id": "criminal-general", "subject": "criminal",       "label": "형법",         "sub": "형법총칙",           "keys": ["형법총칙", "형법총론"]},
    {"id": "criminal-special", "subject": "criminal",       "label": "형법",         "sub": "형법각칙",           "keys": ["형법각칙", "형법각론"]},
    {"id": "commercial",       "subject": "commercial",     "label": "상법",         "sub": "",                   "keys": ["상법", "회사법", "공정거래", "보험법", "해상법", "어음", "수표법"]},   # 회사법·공정거래법도 상법으로 본다
    {"id": "ip",               "subject": "ip",             "label": "지식재산권법", "sub": "",                   "keys": ["지식재산", "특허법", "저작권법", "상표법"]},
]
ANNUAL_FIELD_IDS = [f["id"] for f in ANNUAL_FIELDS]
ANNUAL_BY_ID = {f["id"]: f for f in ANNUAL_FIELDS}
# 제목 매칭 순서: '민법(가족법)'·'형법 총칙'처럼 겹치는 낱말이 있으므로 좁은 분야부터 본다.
# ANNUAL_FIELDS 에 새로 넣은 분야는 아래 목록에 없어도 맨 앞에서 먼저 검사된다(넓은 분야의 keys 와 겹치면 그쪽 keys 를 정리할 것).
_MATCH_ORDER = ["family", "criminal-general", "criminal-special", "ip", "commercial", "administrative", "constitution", "civil"]
_MATCH_ORDER = [i for i in ANNUAL_FIELD_IDS if i not in _MATCH_ORDER] + [i for i in _MATCH_ORDER if i in ANNUAL_BY_ID]
_norm = lambda s: re.sub(r"[\s()（）\[\]·・.,]", "", s or "")   # noqa: E731 — 제목·분야명 비교용
# 기사 제목으로 정하지 못할 때 과목으로 정하는 기본 분야(형법은 총칙·각칙을 고를 수 없으므로 없음)
_DEFAULT_FIELD = {"constitution": "constitution", "administrative": "administrative", "civil": "civil", "commercial": "commercial", "ip": "ip"}
# 연도 선택 버튼의 범위(화면에는 최신 연도부터 역순). 등록부에 더 최근 연도가 있으면 build_data.py 가 자동으로 늘린다.
ANNUAL_YEARS = (2020, 2025)
# 헌법재판소 주요결정 페이지의 선고연도 버튼 범위(2010년 선고 사건부터 수록). 같은 방식으로 등록부의 선고일에 맞춰 자동으로 늘어난다.
CCOURT_YEARS = (2010, 2026)
# 대법원 전원합의체 페이지의 시대 탭: ENBANC_YEARS[0] 이후는 '2020년 이후' 하나, 그 앞은 대법원이 처음 선고한 해(ENBANC_FROM)가 든
# 연대까지 10년 단위(2010년대 · 2000년대 · … · 1940년대). 시대 탭을 고르면 그 시대의 개별 연도 버튼이 아래 줄에 나온다.
# ENBANC_YEARS[0] 은 연대의 첫 해(10의 배수)로 둔다. 등록부 선고일이 범위 밖이면 build_data.py 가 그쪽으로 넓힌다.
ENBANC_YEARS = (2020, 2026)
ENBANC_FROM = 1948


def label_of(subject_id):
    return BY_ID.get(subject_id, {}).get("label", subject_id)


def resolve(name):
    """'civil' 또는 '민법' → 'civil'. 모르는 값이면 ValueError (argparse type 으로 쓰기 좋다)."""
    name = (name or "").strip()
    if name in BY_ID:
        return name
    for s in SUBJECTS:
        if name in (s["label"], s["folder"]) and name:
            return s["id"]
    raise ValueError(f"알 수 없는 과목: {name!r} (가능: {', '.join(SUBJECT_IDS)})")


def resolve_standard(name):
    """resolve() 와 같되 표준판례 과목(헌법·행정법·민법·형법·상법)만 허용."""
    sid = resolve(name)
    if sid not in STANDARD_IDS:
        raise ValueError(f"표준판례 과목이 아닙니다: {name!r} (가능: {', '.join(STANDARD_IDS)})")
    return sid


def guess_from_filename(path):
    """'표준판례(2023년 개정판)_상법.pdf' 처럼 파일명에 든 한글 과목명으로 과목 id 를 추정. 없으면 None."""
    import os
    stem = os.path.basename(path)
    hits = [s for s in sorted(STANDARD_SUBJECTS, key=lambda s: -len(s["folder"])) if s["folder"] in stem]
    return hits[0]["id"] if hits else None


def resolve_field(name):
    """'family' 또는 '가족법'·'형법각칙'·'민법 가족법'·'민법(총칙·물권법·채권법)'·'공정거래법'(→ 상법) → 분야 id.
    화면 이름이 아니면 기사 제목과 같은 규칙(guess_field)으로 찾는다. 모르는 값이면 ValueError (argparse type 용)."""
    name = (name or "").strip()
    if name in ANNUAL_BY_ID:
        return name
    compact = _norm(name)
    for f in ANNUAL_FIELDS:
        if compact and compact in (_norm(f["label"] + f["sub"]), _norm(f["sub"]) or None, None if f["sub"] else _norm(f["label"])):
            return f["id"]
    fid = guess_field(name)
    if fid:
        return fid
    raise ValueError(f"알 수 없는 분야: {name!r} (가능: {', '.join(ANNUAL_FIELD_IDS)})")


def article_part(article):
    """'[2025년 분야별 중요판례분석] (3) 민법(총칙·물권법)' → '민법(총칙·물권법)' (연재 머리·순번 제거).
    2023년 연재처럼 제목 뒤에 붙은 필자('(22) 언론법 - 김기수 고법판사(특허법원)')도 떼어 낸다 — 소속명이 분야로 오인되지 않게."""
    part = re.sub(r"^\s*\[[^\]]*\]\s*", "", article or "")
    part = re.sub(r"^[\(（]\s*\d+\s*[\)）]\s*|^\d+\s*[.)]\s*", "", part)
    return re.sub(r"\s+[-–—?‐]\s+.*$", "", part).strip()


def article_year(article):
    """기사 제목의 '[2025년 분야별 중요판례분석]' 에서 연도. 없으면 None."""
    m = re.search(r"(\d{4})\s*년\s*분야별", article or "")
    return int(m.group(1)) if m else None


def guess_field(article="", subject=None):
    """기사 제목(연재 머리·순번 포함 가능)과 과목으로 분야 id 를 추정. 정할 수 없으면 None.
    제목이 있는데 어느 분야 낱말도 없으면(민사소송법·노동법 등 대상 밖 기사) None, 제목이 없을 때만 과목의 기본 분야를 쓴다
    (형법은 총칙·각칙을 고를 수 없으므로 제목 없이는 None)."""
    compact = _norm(article_part(article))
    if compact:
        return next((fid for fid in _MATCH_ORDER if any(k in compact for k in ANNUAL_BY_ID[fid]["keys"])), None)
    return _DEFAULT_FIELD.get(subject)
