"""숫자 검산 표 모양 테스트 (합성 예제): 합계가 첫 칸인 표, ▲·▼ 부호, 연도가 첫 행인 로드맵, 두 단 머리칸.

공개 전 기획보고서 실행에서 이 모양들이 불일치 9건으로 오탐됐고, 그 오탐이 공방·최종 결정의 핵심 쟁점이 됐다.
"""

from rdagents.dataflows import budget_check as bc


def test_total_in_first_column_and_triangle_signs():
    lines = ["|구분|합계|가 분야|나 분야|다 분야|", "|---|---|---|---|---|",
             "|올해(억원)|660|110|250|300|", "|작년(억원)|600|100|200|300|",
             "|증감률(%)|▲10.0|▲10.0|▲25.0|0.0|"]
    rep = bc.check(lines)
    assert rep.findings == [] and rep.checks >= 2
    assert bc.parse_cell("▲10.0")[0] == 10.0 and bc.parse_cell("▼3.5")[0] == -3.5 and bc.parse_cell("△7")[0] == -7
    wrong = ["|구분|합계|가 분야|나 분야|", "|---|---|---|---|", "|올해(억원)|500|110|250|"]
    assert [(f.kind, f.computed) for f in bc.check(wrong).findings] == [("행 합계", "360")]


def test_roadmap_with_year_row_task_rows_and_subtotals():
    lines = ["(단위: 백만원)",
             "|내역사업||과제명|및 연차별|예산|합계|", "|---|---|---|---|---|---|",
             "||2030|2031|2032|2033||",
             "||가상 과제|하나 기술|개발|||",
             "|내역 A|100|200|300|400|1,000|",
             "||가상 과제|둘 기술|개발|||",
             "||50|50|50|50|200|",
             "|내역 합계|150|250|350|450|1,200|",
             "||가상 과제|셋 실증||||",
             "|내역 B|300|300|||600|",
             "|내역 합계|300|300|||600|",
             "|합계|450|550|350|450|1,800|"]
    assert bc.check(lines).findings == []
    lines[-1] = "|합계|450|550|350|450|1,900|"
    found = {(f.kind, f.stated, f.computed) for f in bc.check(lines).findings}
    assert found == {("열 합계", "1,900", "1,800"), ("행 합계", "1,900", "1,800"), ("원인 칸 추정", "1,900", "1,800")}


def test_two_level_header_skips_row_sums():
    lines = ["|연도|합|계|가 지원|가 지원|나 지원|나 지원|", "|---|---|---|---|---|---|---|",
             "||건수|금액|건수|금액|건수|금액|",
             "|2030|30|90|10|40|20|50|", "|2031|12|33|4|11|8|22|"]
    assert not [f for f in bc.check(lines).findings if f.kind == "행 합계"]
