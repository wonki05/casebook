"""사건번호·선고일·법원 인식 공통 모듈 (pdf_standard_cases.py, annual_cases.py, add_cases.py 가 공유)."""
import re

# 대법원 사건부호(민사 다/다카/므/마/그/자/스/라/누/두/도/모/오/우/후/재 등)와 헌법재판소(헌가~헌사)
CASE_RE = re.compile(
    r'(?<![0-9])(\d{2}|\d{4})\s?'
    r'(헌[가나다라마바사아자차]|다카|다|도|두|마|므|누|라|바|카|그|재|스|자|노|모|보|오|우|후|히|초|허|후|'
    r'고합|고단|고정|구합|구단|가합|가단|가소|나|너|더|러|버|감노|감도|감고|로|루|조|초기|초보|초재|즈|흐)'
    r'\s?(\d{1,7})(?![0-9])'
)
DATE_RE = re.compile(r'(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[.일]?')
COURT_RE = re.compile(r'(헌법재판소|대법원|고등법원|지방법원|행정법원|가정법원|특허법원)')


def is_cc(case_number: str) -> bool:
    return '헌' in case_number


def romanize(case_number: str) -> str:
    """id 생성용: 2022도5937 → 2022do5937, 2026헌라3 → 2026heolla3 (기존 id 관례와 동일)."""
    m = CASE_RE.search(case_number.replace(' ', ''))
    if not m:
        return re.sub(r'[^0-9a-z]', '', case_number.lower())
    y, kind, n = m.groups()
    table = {'헌가': 'heolga', '헌나': 'heolna', '헌다': 'heolda', '헌라': 'heolla', '헌마': 'heolma', '헌바': 'heolba', '헌사': 'heolsa', '헌아': 'heola',
             '도': 'do', '다': 'da', '두': 'du', '마': 'ma', '므': 'meu', '누': 'nu', '라': 'ra', '바': 'ba', '카': 'ka', '그': 'geu', '재': 'jae', '스': 'seu', '자': 'ja',
             '노': 'no', '모': 'mo', '보': 'bo', '오': 'o', '우': 'u', '후': 'hu', '히': 'hi', '초': 'cho', '허': 'heo', '다카': 'daka'}
    return f"{y}{table.get(kind, kind)}{n}"


def lookup_key(case_number: str) -> str:
    """병합사건(2023헌바274·351, 2023헌바234등, 2024헌마990·2026헌바197) → 대표 사건번호."""
    return re.split(r'[·,/]|등|\s', case_number.strip())[0].strip()


def norm_date(y, m, d) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def find_cases(text: str, window: int = 120):
    """텍스트에서 사건번호 후보를 찾아 [{caseNumber, court, date, enBanc, pos, snippet}] 반환 (중복 제거, 등장 순).
    선고일: 사건번호 앞쪽(가까운 순)의 날짜를 우선, 없으면 바로 뒤의 날짜. 전원합의체: 사건번호 바로 뒤 30자 안의 표기."""
    out, seen = [], set()
    for m in CASE_RE.finditer(text):
        cn = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        if cn in seen:
            continue
        seen.add(cn)
        a, b = max(0, m.start() - window), min(len(text), m.end() + window)
        snip = text[a:b].replace('\n', ' ')
        before = text[a:m.start()]
        after = text[m.end():m.end() + 30]
        court = '헌법재판소' if is_cc(cn) else ('대법원' if ('대법원' in before[-60:] or '대판' in before[-20:] or '대법원' in after) else '')
        dates = [(d.start() + a, d.end() + a, d.groups()) for d in DATE_RE.finditer(text[a:b])]
        prev = [d for d in dates if d[1] <= m.start()]
        nxt = [d for d in dates if d[0] >= m.end()]
        pick = prev[-1] if prev else (nxt[0] if nxt else None)
        date = norm_date(*pick[2]) if pick else ''
        out.append({'caseNumber': cn, 'court': court, 'date': date, 'enBanc': '전원합의체' in after or '전원합의체' in before[-25:], 'pos': m.start(), 'snippet': snip.strip()})
    return out
