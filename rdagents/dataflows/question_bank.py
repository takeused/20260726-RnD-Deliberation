# 질의 은행 — 전형 질의 패턴 시드 + 검증을 거친 실제 질의를 축적해 예측 질의를 그라운딩
"""예상 질의가 LLM 일반론에 머물지 않도록 참고 코퍼스를 프롬프트에 주입한다.
시드(question_bank_seed/)는 전형 질의 패턴이고, --verify-questions를 거친
실제 질의가 사용자 은행 디렉터리에 자동 축적되어 회차가 쌓일수록 실전 비중이 커진다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def load_question_bank(
    bank_dirs: list[str | Path],
    max_chars: int = 8000,
) -> str:
    """은행 디렉터리들의 md 파일을 모아 참고 텍스트로 반환. 없으면 빈 문자열.

    최신 실전 질의가 잘리지 않도록 사용자 은행(뒤쪽 디렉터리)을 앞에 배치한다.
    """
    sections: list[str] = []
    for bank_dir in reversed([Path(d) for d in bank_dirs if d]):
        if not bank_dir.is_dir():
            continue
        for path in sorted(bank_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if text:
                sections.append(f"### 출처 파일: {path.name}\n{text}")
    if not sections:
        return ""
    combined = "\n\n".join(sections)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n(분량 제한으로 이하 생략)"
    return combined


def append_actual_questions(
    bank_dir: str | Path,
    project_id: str,
    actual_questions_text: str,
) -> Path:
    """검증에 사용된 실제 질의를 사용자 은행에 축적."""
    bank_dir = Path(bank_dir)
    bank_dir.mkdir(parents=True, exist_ok=True)
    out = bank_dir / f"실제질의_{project_id}.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n## {stamp} 실제 심의 질의\n\n{actual_questions_text.strip()}\n"
    with open(out, "a", encoding="utf-8") as f:
        f.write(block)
    return out
