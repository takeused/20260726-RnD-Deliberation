"""기획보고서 검색 순위 테스트 (합성 보고서).

검색 점수가 '질의 단어가 나온 횟수의 합'이면 '기술·사업'처럼 어디에나 나오는 단어를 많이 담은 조각이 늘 이긴다.
공개 전 기획보고서 실행에서 모든 분석가가 부르는 기술 상세 도구가 매번 같은 두 조각만 돌려받았고, 분석 전체가
그 두 곳(사업 일부 과제)에 쏠렸다.
"""

import re

from rdagents.dataflows import project_loader as pl


def _ranges(out: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in re.findall(r"L(\d+)-L(\d+)\]", out)]


def _report(tmp_path, paragraphs: list[str]) -> pl.ProjectContext:
    """문단 사이에 빈 줄을 두 줄씩 넣어 문단 하나가 조각 하나가 되게 한다 (조각 최소 크기 200자, 문단은 200자 미만)."""
    assert all(len(p) < 190 for p in paragraphs)
    path = tmp_path / "합성보고서.md"
    path.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    pl.set_current_report(str(path), project_id="retrieval", chunk_chars=200, retrieval_top_k=1)
    return pl._current_context.get()


def _chunk_at(ctx: pl.ProjectContext, start: int) -> str:
    return next(c.text for c in ctx.chunks if c.start_line == start)


def test_rare_query_term_beats_repeated_common_word(tmp_path):
    """'TRL'이 실제로 나오는 조각이 '기술'만 여러 번 나오는 조각보다 앞선다."""
    filler = "·" * 120  # 문단을 각각 다른 조각으로 나누기 위한 채움 (검색어 아님)
    ctx = _report(tmp_path, [
        "기술 기술 기술 기술 기술 개발 기술 확보 기술 융합 기술 고도화 기술 보급 기술 실증. " + filler,
        "가 과제의 목표는 TRL 7 이상 달성이다. 핵심 기술은 실증으로 검증한다. " + filler,
        "추진 일정과 예산 배분을 정리한다. 연차별로 집행한다. " + filler,
    ])
    assert len(ctx.chunks) == 3
    (start, _), = _ranges(pl._render_search(ctx, "기술 상세(TRL, 핵심기술)"))
    assert "TRL" in _chunk_at(ctx, start)


def test_long_chunk_does_not_win_on_length_alone(tmp_path):
    """같은 단어를 한 번씩 담았으면 짧은 조각이 긴 조각에 밀리지 않는다 (조각 길이 보정). 긴 조각이 먼저 나와도."""
    long = "성과지표 외에도 " + " ".join(f"설명{i}" for i in range(36))
    ctx = _report(tmp_path, [long, "성과지표 정의." + "·" * 120])
    assert len(ctx.chunks) == 2 and len(ctx.chunks[0].text) > len(ctx.chunks[1].text)
    (start, _), = _ranges(pl._render_search(ctx, "성과지표"))
    assert start == ctx.chunks[1].start_line
