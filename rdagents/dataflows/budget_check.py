"""숫자 검산 (규칙 기반, LLM 없음): 기획보고서의 표와 본문 숫자를 코드로 다시 계산해 서로 맞는지 본다.

표의 열 합계·행 합계·단가×수량·비율, 본문의 '총 120억 (30억, 50억 …)' 합계와 'A에서 B로 X% 증가' 증감률,
본문 금액과 표 합계를 대조한다. 반올림 오차는 자릿수에 맞춰 허용하고, 행·열이 같은 크기로 어긋나거나
적힌 비율로 거꾸로 계산해 합계가 맞으면 틀린 칸을 추정한다. 서로 '맞는지'만 보며 타당성은 판단하지 않는다.

출처: 학습 저장소 langgraph-learning-examples의 budget_check.py(27번 예제)를 옮겼다. 명령줄·PDF 읽기를 빼고,
사전 점검(plan_precheck)에 붙일 출력(render_section, brief_lines)을 더했다.
NDMI 공개 보고서에서 통계표 1개의 비율 4곳·열 합계 2곳 불일치를 찾았다 (원본 PDF 숫자 그대로).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNIT_WON = {"원": 1, "천원": 1e3, "만원": 1e4, "백만원": 1e6, "천만원": 1e7, "억원": 1e8, "억": 1e8, "조원": 1e12, "조": 1e12}
TOTAL_LABEL = re.compile(r"^(?:총\s*계|합\s*계|총\s*합\s*계|계|총액|전체)$")
SUBTOTAL_LABEL = re.compile(r"소\s*계")
RATIO_HEADER = re.compile(r"비율|비중|구성비|점유율|%")
PRICE_HEADER, QTY_HEADER = re.compile(r"단가"), re.compile(r"수량|개수|인원|대수")
AMOUNT_HEADER = re.compile(r"금액|소요액|예산|사업비|합계|계")
CELL_NUMBER = re.compile(r"^([△▲-])?\s*(\d[\d,]*(?:\.\d+)?)\s*%?$")

# 본문 금액·수량: "2조649.9억 원", "5,872.5억 원", "12만 명", "40개소"
AMT = r"(?:\d[\d,]*(?:\.\d+)?\s*조\s*)?\d[\d,]*(?:\.\d+)?\s*(?:천만|백만|억|만|천)?\s*(?:원|명|개소|개|건|톤|가구|ha)?"
# 두 값 사이의 연도("40개소에서 2024년 52개소로")는 건너뜀
GROWTH = re.compile(rf"(?P<a>{AMT})\s*에서\s*(?:\d{{4}}\s*년\s*)?(?P<b>{AMT})\s*(?:으로|로)\s*(?P<p>\d[\d,]*(?:\.\d+)?)\s*%\s*"
                    r"(?P<dir>증가|감소|상승|하락|늘|줄)")
TOTAL_WITH_PARTS = re.compile(rf"총\s*(?:사업비|연구비|예산|소요\s*예산)?\s*[:：]?\s*(?P<total>{AMT})\s*\((?P<parts>[^)]*)\)")
COMPOSITION = re.compile(r"(?:구성|내역|배분)\s*[:：]\s*(?P<parts>.+)")
# 이름은 숫자로 시작할 수 있지만(1차년도) 숫자 아닌 글자로 끝나야 금액과 구분된다
LABELED_AMT = re.compile(rf"(?P<label>[^,()]*?[^\s\d,().])\s*(?P<amt>{AMT})(?=\s*(?:,|$))")


@dataclass
class Finding:
    kind: str           # 열 합계 / 행 합계 / 단가×수량 / 비율 / 본문 합계 / 증감률 / 본문↔표
    line: int
    where: str          # 표 이름·칸 또는 본문 문장 앞부분
    stated: str
    computed: str
    note: str = ""


@dataclass
class Table:
    start: int                                  # 머리행 줄 번호 (1부터)
    name: str
    header: list[str]
    rows: list[tuple[int, list[str]]]           # (줄 번호, 칸들)
    unit: str | None = None                     # "(단위: 백만원)" 같은 표 단위

    def col_unit(self, c: int) -> str | None:
        """머리칸의 괄호 단위(예: '금액(억 원)')가 표 단위보다 우선."""
        m = re.search(r"\(([^)]*)\)", self.header[c])
        if m and (u := norm_unit(m.group(1))):
            return u
        return self.unit


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checks: int = 0                              # 계산해 본 횟수 (통과 포함)
    tables: int = 0


def norm_unit(text: str) -> str | None:
    t = re.sub(r"\s", "", text)
    for u in sorted(UNIT_WON, key=len, reverse=True):
        if u in t:
            return u
    return None


def parse_cell(text: str) -> tuple[float | None, int]:
    """표 칸 -> (값, 소수 자릿수). '-'·빈칸은 0, 숫자가 아니면 None."""
    t = re.sub(r"\*\*|<br>", "", text).strip()
    if t in ("", "-", "–", "—"):
        return 0.0, 0
    m = CELL_NUMBER.match(t)
    if not m:
        return None, 0
    digits = m.group(2).replace(",", "")
    value = float(digits) * (-1 if m.group(1) else 1)
    return value, len(digits.split(".")[1]) if "." in digits else 0


def parse_amount(text: str) -> tuple[float, int, str]:
    """본문 금액 -> (원 또는 개수 기준 값, 소수 자릿수, 단위 표시). '2조649.9억 원' -> 2,064,990,000,000원."""
    t = re.sub(r"\s", "", text)
    jo = re.match(r"(\d[\d,]*(?:\.\d+)?)조", t)
    rest = t[jo.end():] if jo else t
    m = re.match(r"(\d[\d,]*(?:\.\d+)?)(천만|백만|억|만|천)?(.*)", rest)
    digits = m.group(1).replace(",", "")
    scale = {"천만": 1e7, "백만": 1e6, "억": 1e8, "만": 1e4, "천": 1e3, None: 1}[m.group(2)]
    value = float(digits) * scale + (float(jo.group(1).replace(",", "")) * 1e12 if jo else 0)
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return value, decimals, (m.group(2) or "") + m.group(3)


def fmt(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def won(x: float) -> str:
    """원 단위 값을 읽기 쉬운 억 원으로."""
    return f"{x / 1e8:,.1f}억 원".replace(".0억", "억")


def split_row(line: str) -> list[str]:
    """표 한 줄 -> 칸들 (굵게 표시 ** 와 줄바꿈 <br>은 지움)."""
    return [re.sub(r"\*\*|<br>", " ", c).strip() for c in line.strip().strip("|").split("|")]


def find_tables(lines: list[str]) -> list[Table]:
    tables, i = [], 0
    while i < len(lines):
        is_sep = i + 1 < len(lines) and re.fullmatch(r"\s*\|?\s*:?-{3,}.*", lines[i + 1] or "")
        if lines[i].lstrip().startswith("|") and is_sep:
            start, header = i + 1, split_row(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = split_row(lines[j])
                rows.append((j + 1, cells + [""] * (len(header) - len(cells))))
                j += 1
            above = lines[max(0, i - 5):i]
            unit = next((norm_unit(m.group(1)) for l in reversed(above) if (m := re.search(r"단위\s*[:：]\s*([^)]*)", l))), None)
            # 표 이름은 번호만 ("표 1.1"): 결과 표의 위치 칸이 길어지지 않게
            caption = next((m.group(0) for l in reversed(above) if (m := re.search(r"표\s*\d+(?:[.-]\d+)*", l))), "")
            tables.append(Table(start, caption or f"L{start} 표", header, rows, unit))
            i = j
        else:
            i += 1
    return tables


def label_of(cells: list[str]) -> str:
    return re.sub(r"\*\*", "", cells[0]).strip()


def numeric_cols(t: Table) -> list[int]:
    """첫 열(항목명)을 뺀, 값이 숫자인 열."""
    cols = []
    for c in range(1, len(t.header)):
        values = [parse_cell(cells[c])[0] for _, cells in t.rows]
        if values and all(v is not None for v in values) and any(v for v in values):
            cols.append(c)
    return cols


def rounding_tol(decimals: int, n: int) -> float:
    """반올림된 값 n개를 더할 때 생길 수 있는 오차."""
    return max(1, n / 2) * 10 ** -decimals + 1e-9


def check_table(t: Table, rep: Report) -> None:
    cols = numeric_cols(t)
    if not cols:
        return
    rep.tables += 1
    ratio_cols = [c for c in cols if RATIO_HEADER.search(t.header[c])]
    amount_cols = [c for c in cols if c not in ratio_cols]
    total_row = next(((ln, cells) for ln, cells in t.rows if TOTAL_LABEL.match(label_of(cells))), None)
    body = [(ln, cells) for ln, cells in t.rows
            if (ln, cells) != total_row and not SUBTOTAL_LABEL.search(label_of(cells))]
    col_off: dict[int, float] = {}
    row_off: dict[int, float] = {}

    # 1. 열 합계: 항목들을 더한 값 = 합계 행
    if total_row:
        for c in amount_cols:
            if not total_row[1][c].strip() or PRICE_HEADER.search(t.header[c]) or QTY_HEADER.search(t.header[c]):
                continue  # 합계 칸이 비었거나 더하는 값이 아님(단가·수량)
            parsed = [parse_cell(cells[c]) for _, cells in body]
            stated, d = parse_cell(total_row[1][c])
            d = max([d] + [p[1] for p in parsed])
            computed = sum(p[0] for p in parsed)
            rep.checks += 1
            if abs(computed - stated) > rounding_tol(d, len(parsed)):
                col_off[c] = computed - stated
                rep.findings.append(Finding("열 합계", total_row[0], f"{t.name} · {t.header[c]}",
                                            fmt(stated, d), fmt(computed, d), f"항목 {len(parsed)}개를 더한 값"))

    # 2. 행 합계: 연차별 값을 더한 값 = '합계' 열 (단가·수량이 있는 표는 더하는 표가 아니라 건너뜀)
    total_col = next((c for c in amount_cols if TOTAL_LABEL.match(re.sub(r"\*\*", "", t.header[c]).strip())), None)
    multiplicative = any(PRICE_HEADER.search(h) or QTY_HEADER.search(h) for h in t.header)
    if total_col and not multiplicative:
        parts = [c for c in amount_cols if c < total_col]
        for ln, cells in t.rows:
            parsed = [parse_cell(cells[c]) for c in parts]
            stated, d = parse_cell(cells[total_col])
            d = max([d] + [p[1] for p in parsed])
            computed = sum(p[0] for p in parsed)
            rep.checks += 1
            if abs(computed - stated) > rounding_tol(d, len(parsed)):
                row_off[ln] = computed - stated
                rep.findings.append(Finding("행 합계", ln, f"{t.name} · {label_of(cells)}",
                                            fmt(stated, d), fmt(computed, d), f"{len(parsed)}개 열을 더한 값"))

    # 3. 원인 칸 추정: 행과 열이 같은 크기로 어긋나면 그 교차 칸 하나가 틀렸을 가능성
    for ln, r_off in row_off.items():
        for c, c_off in col_off.items():
            if abs(r_off - c_off) < 1e-9:
                cells = dict(t.rows)[ln]
                rep.findings.append(Finding("원인 칸 추정", ln, f"{t.name} · {label_of(cells)} × {t.header[c]}",
                                            cells[c], fmt(parse_cell(cells[c])[0] - r_off),
                                            "행 합계와 열 합계가 같은 크기로 어긋남 -> 이 칸만 고치면 둘 다 맞음"))

    # 4. 단가 × 수량 = 금액
    price = next((c for c in cols if PRICE_HEADER.search(t.header[c])), None)
    qty = next((c for c in cols if QTY_HEADER.search(t.header[c])), None)
    amount = next((c for c in cols if c not in (price, qty) and AMOUNT_HEADER.search(t.header[c])), None)
    if price and qty and amount:
        for ln, cells in body:
            (p, _), (q, _), (a, d) = parse_cell(cells[price]), parse_cell(cells[qty]), parse_cell(cells[amount])
            if not (p and q):
                continue
            rep.checks += 1
            computed = p * q
            if abs(computed - a) > rounding_tol(d, 1):
                ratio = computed / a if a else 0
                note = "자릿수가 10의 거듭제곱만큼 다름: 단가와 금액의 단위가 다른지 확인" \
                    if a and abs(ratio - round(ratio)) < 1e-9 and round(ratio) in (10, 100, 1000, 10000) else ""
                rep.findings.append(Finding("단가×수량", ln, f"{t.name} · {label_of(cells)}",
                                            fmt(a, d), fmt(computed, d), f"{fmt(p)} × {fmt(q)}" + (f" ({note})" if note else "")))

    # 5. 비율 = 값 / 합계 × 100 (왼쪽에서 가장 가까운 금액 열 기준)
    for rc in ratio_cols:
        base = max((c for c in amount_cols if c < rc), default=None)
        if base is None:
            continue
        denom = parse_cell(total_row[1][base])[0] if total_row else sum(parse_cell(cells[base])[0] for _, cells in body)
        if not denom:
            continue
        wrong = []                                    # (줄, 칸 이름, 적힌 값, 비율로 거꾸로 계산한 값)
        for ln, cells in body:
            stated, d = parse_cell(cells[rc])
            if cells[rc].strip() in ("", "-"):
                continue
            value = parse_cell(cells[base])[0]
            computed = value / denom * 100
            rep.checks += 1
            if abs(computed - stated) > 10 ** -d + 1e-9:   # 마지막 자리 한 칸까지는 반올림·버림 차이로 봄
                implied = stated * denom / 100
                wrong.append((ln, label_of(cells), value, implied, d))
                rep.findings.append(Finding("비율", ln, f"{t.name} · {label_of(cells)} · {t.header[rc]}",
                                            f"{fmt(stated, d)}%", f"{computed:.{max(d, 1)}f}%",
                                            f"{cells[base]} ÷ {fmt(denom)} × 100 (적힌 비율이면 값은 약 {fmt(implied)})"))
        # 6. 원인 칸 추정 (비율): 어긋난 칸을 '적힌 비율로 거꾸로 계산한 값'으로 바꿔 열 합계까지 맞으면,
        #    비율이 아니라 그 칸의 값이 틀렸을 가능성이 크다. 합계가 여전히 안 맞으면 추정하지 않는다
        if wrong and base in col_off:
            fixed = col_off[base] - sum(v - implied for _, _, v, implied, _ in wrong)
            tol = sum(0.5 * 10 ** -d * denom / 100 for *_, d in wrong) + rounding_tol(0, len(body))
            if abs(fixed) <= tol:
                for ln, label, v, implied, _ in wrong:
                    rep.findings.append(Finding("원인 칸 추정", ln, f"{t.name} · {label} × {t.header[base]}",
                                                fmt(v), f"약 {fmt(implied)}",
                                                "적힌 비율로 거꾸로 계산한 값으로 바꾸면 열 합계도 맞음 -> 이 칸의 값이 틀렸을 가능성"))


def check_text(lines: list[str], tables: list[Table], rep: Report) -> None:
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("|"):
            continue
        text = re.sub(r"^[-*#\s]+", "", line)
        snippet = text[:30] + ("…" if len(text) > 30 else "")

        # 1. 'A에서 B로 X% 증가/감소'
        for m in GROWTH.finditer(line):
            a, _, _ = parse_amount(m.group("a"))
            b, _, _ = parse_amount(m.group("b"))
            stated = float(m.group("p").replace(",", ""))
            d = len(m.group("p").split(".")[1]) if "." in m.group("p") else 0
            if not a:
                continue
            computed = (b - a) / a * 100
            if m.group("dir") in ("감소", "하락", "줄"):
                computed = -computed
            rep.checks += 1
            if abs(computed - stated) > 10 ** -d + 1e-9:
                rep.findings.append(Finding("증감률", i, snippet, f"{m.group('p')}% {m.group('dir')}",
                                            f"{computed:.{max(d, 1)}f}%", f"({m.group('b').strip()} − {m.group('a').strip()}) ÷ {m.group('a').strip()}"))

        # 2. '총 120억 원 (1차년도 30억, …)' 괄호 안 금액의 합
        if m := TOTAL_WITH_PARTS.search(line):
            total, d, _ = parse_amount(m.group("total"))
            parts = [(p.group("label").strip(), parse_amount(p.group("amt"))) for p in LABELED_AMT.finditer(m.group("parts"))]
            if len(parts) >= 2:
                computed = sum(v for _, (v, _, _) in parts)
                rep.checks += 1
                if abs(computed - total) > 1e-6 * total:
                    rep.findings.append(Finding("본문 합계", i, snippet, won(total), won(computed),
                                                " + ".join(f"{lab} {won(v)}" for lab, (v, _, _) in parts)))
                cross_check(i, snippet, total, parts, tables, rep)

        # 3. '비목 구성: …' 금액들의 합 = 앞서 나온 총사업비
        elif (m := COMPOSITION.search(line)) and (total := first_total(lines)):
            parts = [(p.group("label").strip(), parse_amount(p.group("amt"))) for p in LABELED_AMT.finditer(m.group("parts"))]
            parts = [(lab, v) for lab, v in parts if v[2].startswith(("억", "백만", "천만", "만", "천", "원"))]
            if len(parts) >= 2:
                computed = sum(v for _, (v, _, _) in parts)
                rep.checks += 1
                if abs(computed - total) > 1e-6 * total:
                    rep.findings.append(Finding("본문 합계", i, snippet, won(total), won(computed), "구성 금액의 합 ≠ 총사업비"))


def first_total(lines: list[str]) -> float | None:
    for line in lines:
        if m := TOTAL_WITH_PARTS.search(line):
            return parse_amount(m.group("total"))[0]
        if m := re.search(rf"총\s*(?:사업비|연구비|예산)\s*[:：]?\s*({AMT})", line):
            return parse_amount(m.group(1))[0]
    return None


def cross_check(line: int, snippet: str, total: float, parts, tables: list[Table], rep: Report) -> None:
    """본문의 총액·연차별 금액을 합계 행이 있는 표(원 단위로 환산 가능한 표)와 대조."""
    for t in tables:
        total_row = next((cells for _, cells in t.rows if TOTAL_LABEL.match(label_of(cells))), None)
        if not total_row:
            continue
        headers = [re.sub(r"\*\*", "", h).strip() for h in t.header]
        for label, (value, _, _) in [("합계", (total, 0, ""))] + parts:
            if label == "합계":
                c = next((c for c in range(1, len(headers)) if TOTAL_LABEL.match(headers[c])), None)
            else:
                c = next((c for c in range(1, len(headers)) if headers[c] == label), None)
            unit = t.col_unit(c) if c else None
            if c is None or unit is None:
                continue
            cell, _ = parse_cell(total_row[c])
            if cell is None:
                continue
            in_won = cell * UNIT_WON[unit]
            rep.checks += 1
            if abs(in_won - value) > 0.005 * value:
                rep.findings.append(Finding("본문↔표", line, f"{snippet} ↔ {t.name} · {headers[c]}",
                                            f"본문 {won(value)}", f"표 {won(in_won)}", f"표 값 {total_row[c]} {unit}"))


def check(lines: list[str]) -> Report:
    rep = Report()
    tables = find_tables(lines)
    for t in tables:
        check_table(t, rep)
    check_text(lines, tables, rep)
    rep.findings.sort(key=lambda f: f.line)
    return rep


def question(f: Finding) -> str:
    return f"L{f.line} {f.where}: 적힌 값은 {f.stated}, 계산 값은 {f.computed}입니다. 어느 쪽이 맞습니까?"


def _cite(source: str, line: int) -> str:
    return f"[출처: {source} L{line}-L{line}]"


def render_section(rep: Report, source: str) -> str:
    """사전 점검표(00b)에 붙일 '숫자 검산' 절."""
    out = ["## 숫자 검산 (표 합계·비율·단가×수량, 본문 합계·증감률)", "",
           f"표 {rep.tables}개, 계산 {rep.checks}건 중 불일치 {len(rep.findings)}건"]
    if rep.findings:
        out += ["", "| 종류 | 위치 | 적힌 값 | 계산 값 | 계산 | 근거 |", "|---|---|---|---|---|---|"]
        out += [f"| {f.kind} | {f.where} | {f.stated} | {f.computed} | {f.note} | {_cite(source, f.line)} |"
                for f in rep.findings]
    out += ["", "- 숫자가 서로 맞는지만 본다. 표의 숫자는 반올림 값이라 자릿수에 맞춘 오차는 허용한다."]
    return "\n".join(out)


def brief_lines(rep: Report, source: str, limit: int = 3) -> list[str]:
    """패널·예상 질의 지시문에 넣을 불일치 요약 (분당 토큰 한도 때문에 limit건까지, 원인 칸 추정 우선)."""
    ranked = sorted(rep.findings, key=lambda f: (f.kind != "원인 칸 추정", f.line))
    return [f"- [숫자 검산] {f.kind}: {f.where} — 적힌 값 {f.stated}, 계산 값 {f.computed}. "
            f"예상 질의: 어느 쪽이 맞습니까? {_cite(source, f.line)}" for f in ranked[:limit]]
