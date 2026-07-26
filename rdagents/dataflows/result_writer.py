# 심의 결과 전체(분석 보고서·토론 전문·최종 결정·예상 질의)를 디스크에 저장하는 모듈
"""저장 구조: {results_dir}/{project_id}/{YYYYMMDD_HHMMSS}/NN_*.md"""

from __future__ import annotations

import json
import re
from html import escape
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from rdagents.agents.schemas import (
    BudgetProposal,
    FinalDecision,
    ReviewPlan,
    render_budget_proposal,
    render_final_decision,
    render_review_plan,
)
from rdagents.dataflows.output_validation import build_validation_report

_ANALYST_FILES = [
    ("tech_value_report", "01a_분석_기술가치.md"),
    ("tech_trend_report", "01b_분석_기술트렌드중복성.md"),
    ("economic_report", "01c_분석_경제재무.md"),
    ("policy_report", "01d_분석_정책부합성.md"),
    ("feasibility_report", "01e_분석_수행체계.md"),
    ("regulatory_report", "01f_분석_규제윤리.md"),
]

_REPORT_FILES = [
    ("00_입력문서_출처.md", "입력 문서·출처"),
    ("01a_분석_기술가치.md", "기술 가치 분석"),
    ("01b_분석_기술트렌드중복성.md", "기술 트렌드·중복성 분석"),
    ("01c_분석_경제재무.md", "경제·재무 분석"),
    ("01d_분석_정책부합성.md", "정책 부합성 분석"),
    ("01e_분석_수행체계.md", "수행체계 분석"),
    ("01f_분석_규제윤리.md", "규제·윤리 분석"),
    ("02_심사공방_전문.md", "심사 공방 전문"),
    ("03_전문위원회_의견.md", "전문위원회 의견"),
    ("04_예산조정안.md", "예산 조정안"),
    ("05_재정검토토론_전문.md", "재정 검토 토론"),
    ("06_최종결정.md", "최종 결정"),
    ("07_예상질의응답.md", "예상 질의응답"),
    ("07b_예상질의.json", "예상 질의 구조화 데이터"),
    ("08_보완권고.md", "보완 권고"),
    ("09_정량평가표.md", "정량 평가표"),
    ("10_불확실성_반대근거.md", "불확실성·반대 근거"),
    ("11_재심의_전후비교.md", "재심의 전후 비교"),
    ("12_실행관측성.md", "실행 관측성"),
    ("14_검증보고서.md", "생성물 근거 검증"),
]


def _render_json_field(raw: str, schema, renderer) -> str:
    """상태에 JSON으로 저장된 구조화 산출물을 마크다운으로 복원. 실패 시 원문 그대로."""
    try:
        return renderer(schema(**json.loads(raw)))
    except Exception:
        return raw


def _clean_markdown_text(value: str) -> str:
    """보고서 본문에서 Markdown 표식만 제거한 안전한 일반 텍스트."""
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"^\s{0,3}[#>]+\s?", "", value)
    return value.strip()


def _inline_html(value: str) -> str:
    return escape(_clean_markdown_text(value)).replace("&lt;br&gt;", "<br>")


def _markdown_to_html(raw: str) -> str:
    """생성물의 Markdown을 읽기용 HTML로 가볍게 변환한다.

    외부 패키지 없이 제목·문단·목록·표를 처리하며, 원문 표현 기호는 노출하지 않는다.
    """
    lines = raw.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line == "---":
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            rows = []
            for row in table_lines:
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                    continue
                rows.append(cells)
            if rows:
                head, *body = rows
                head_html = "".join(f"<th>{_inline_html(cell)}</th>" for cell in head)
                body_html = "".join(
                    "<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in row) + "</tr>"
                    for row in body
                )
                blocks.append(f'<div class="table-scroll"><table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table></div>')
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 3)
            tag = min(level + 2, 6)
            blocks.append(f"<h{tag}>{_inline_html(line.lstrip('#').strip())}</h{tag}>")
            index += 1
            continue
        if re.match(r"^[-*]\s+", line):
            items = []
            while index < len(lines) and re.match(r"^[-*]\s+", lines[index].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[index].strip()))
                index += 1
            blocks.append("<ul>" + "".join(f"<li>{_inline_html(item)}</li>" for item in items) + "</ul>")
            continue
        if re.match(r"^\d+[.)]\s+", line):
            items = []
            while index < len(lines) and re.match(r"^\d+[.)]\s+", lines[index].strip()):
                items.append(re.sub(r"^\d+[.)]\s+", "", lines[index].strip()))
                index += 1
            blocks.append("<ol>" + "".join(f"<li>{_inline_html(item)}</li>" for item in items) + "</ol>")
            continue
        paragraph = [line]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if not next_line or next_line == "---" or next_line.startswith("#") or next_line.startswith("|") or re.match(r"^[-*]\s+|^\d+[.)]\s+", next_line):
                break
            paragraph.append(next_line)
            index += 1
        blocks.append(f"<p>{_inline_html(' '.join(paragraph))}</p>")
    return "\n".join(blocks) or "<p>내용이 없습니다.</p>"


def _find_label(raw: str, label: str) -> str:
    match = re.search(rf"(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*:\s*(.+)", raw)
    return _clean_markdown_text(match.group(1)) if match else "확인 필요"


def _write_html_report(out_dir: Path, project_id: str, metadata: dict) -> Path:
    """국가연구개발사업 심의보고서 형식의 읽기용 HTML 리포트를 생성한다."""
    documents = {
        filename: (out_dir / filename).read_text(encoding="utf-8")
        for filename, _ in _REPORT_FILES
        if (out_dir / filename).exists()
    }
    final = documents.get("06_최종결정.md", "")
    decision = _find_label(final, "최종 심의 결정")
    summary = _find_label(final, "요약")
    approved_budget = _find_label(final, "최종 승인 예산")
    budget_from_summary = re.search(r"원안\s*([0-9][0-9,]*(?:\.\d+)?)\s*억\s*원", final)
    if budget_from_summary:
        approved_budget = f"원안 {budget_from_summary.group(1)}억 원 유지"
    tech_value = documents.get("01a_분석_기술가치.md", "")
    project_name = _find_label(tech_value, "사업명")
    if project_name == "확인 필요":
        project_name = project_id
    source_manifest = documents.get("00_입력문서_출처.md", "")
    validation_status = _find_label(documents.get("14_검증보고서.md", ""), "검증 상태")
    execution_id = escape(str(metadata.get("execution_id", "알 수 없음")))
    provider = escape(str(metadata.get("provider", "알 수 없음")))
    deep_model = escape(str(metadata.get("deep_model", "알 수 없음")))
    review_year = escape(str(metadata.get("review_year", "알 수 없음")))

    appendix_items = []
    appendix_files = [
        ("01a_분석_기술가치.md", "기술가치 분석"),
        ("01b_분석_기술트렌드중복성.md", "기술트렌드·유사중복 분석"),
        ("01c_분석_경제재무.md", "경제·재무 분석"),
        ("01d_분석_정책부합성.md", "정책부합성 분석"),
        ("01e_분석_수행체계.md", "수행체계 분석"),
        ("01f_분석_규제윤리.md", "규제·윤리 분석"),
        ("02_심사공방_전문.md", "심사 공방 전문"),
        ("05_재정검토토론_전문.md", "재정 검토 토론"),
        ("09_정량평가표.md", "정량 평가표"),
        ("10_불확실성_반대근거.md", "불확실성·반대 근거"),
        ("12_실행관측성.md", "실행 관측성"),
        ("14_검증보고서.md", "생성물 근거 검증"),
    ]
    for filename, title in appendix_files:
        if raw := documents.get(filename):
            appendix_items.append(
                f'<details><summary>{escape(title)} <span>{escape(filename)}</span></summary>'
                f'<div class="detail-body">{_markdown_to_html(raw)}</div></details>'
            )

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#12334a">
<title>국가연구개발사업 심의결과 보고서 - {escape(project_name)}</title>
<style>
:root {{ color-scheme:light; --navy:#12334a; --blue:#176c9b; --teal:#06756f; --ink:#17212b; --muted:#61707e; --line:#d7e0e5; --paper:#fff; --bg:#eff3f4; --amber:#956600; --amber-bg:#fff6dc; }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.72 "Noto Sans KR","Malgun Gothic",system-ui,sans-serif; }}
.skip-link {{ position:absolute; left:-999px; top:0; }} .skip-link:focus {{ left:16px; top:16px; z-index:20; background:#fff; padding:8px 12px; border-radius:4px; color:var(--navy); }}
.page {{ max-width:1380px; margin:0 auto; padding:30px 24px 72px; }} .masthead {{ border-top:6px solid var(--teal); background:var(--paper); padding:30px 36px 26px; box-shadow:0 8px 20px #17364a12; }}
.kicker {{ margin:0 0 8px; color:var(--teal); font-size:13px; font-weight:800; letter-spacing:.08em; }} h1 {{ margin:0; color:var(--navy); font-size:clamp(28px,4vw,42px); line-height:1.25; text-wrap:balance; }} .subtitle {{ margin:12px 0 0; color:var(--muted); }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:22px; padding-top:16px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; }} .meta strong {{ color:var(--ink); }}
.layout {{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:26px; margin-top:26px; }} .toc {{ position:sticky; top:18px; align-self:start; background:var(--paper); border:1px solid var(--line); padding:16px; }} .toc p {{ margin:0 0 9px; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.06em; }} .toc a {{ display:block; padding:7px 8px; color:#28465a; text-decoration:none; border-left:2px solid transparent; }} .toc a:hover {{ color:var(--teal); background:#f2f8f8; }} .toc a:focus-visible {{ outline:3px solid #63a7cc; outline-offset:2px; }}
.content {{ min-width:0; }} section {{ scroll-margin-top:20px; background:var(--paper); border:1px solid var(--line); margin-bottom:18px; padding:28px 32px; box-shadow:0 3px 10px #17364a08; }} h2 {{ margin:0 0 18px; color:var(--navy); font-size:24px; line-height:1.35; border-bottom:2px solid #dcecef; padding-bottom:10px; text-wrap:balance; }} h3 {{ margin:26px 0 10px; color:#185475; font-size:18px; }} h4 {{ margin:20px 0 8px; font-size:16px; }} p {{ margin:0 0 13px; }}
.decision {{ border-top:5px solid var(--teal); }} .decision-grid {{ display:grid; grid-template-columns:210px 1fr; gap:20px; align-items:start; }} .verdict {{ padding:20px; background:var(--amber-bg); border:1px solid #edd38d; }} .verdict span {{ display:block; color:var(--amber); font-size:12px; font-weight:800; letter-spacing:.06em; }} .verdict strong {{ display:block; margin-top:7px; color:#5b4200; font-size:25px; }} .decision-summary {{ font-size:17px; }}
.facts {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }} .fact {{ border:1px solid var(--line); padding:16px; background:#fbfcfc; }} .fact dt {{ color:var(--muted); font-size:12px; font-weight:800; }} .fact dd {{ margin:5px 0 0; font-size:17px; font-weight:700; }}
.notice {{ border-left:4px solid var(--blue); background:#eef8fb; padding:15px 17px; }} ul,ol {{ margin:8px 0 15px; padding-left:22px; }} li {{ margin:5px 0; }} .table-scroll {{ overflow-x:auto; margin:13px 0 20px; }} table {{ width:100%; border-collapse:collapse; min-width:600px; font-size:14px; }} th,td {{ border:1px solid var(--line); padding:10px 12px; vertical-align:top; text-align:left; }} th {{ background:#eaf3f5; color:#17435d; font-weight:800; }}
details {{ border:1px solid var(--line); margin:10px 0; background:#fcfdfd; }} summary {{ cursor:pointer; padding:14px 16px; color:#173f56; font-weight:800; touch-action:manipulation; }} summary:hover {{ background:#f0f7f8; }} summary:focus-visible {{ outline:3px solid #63a7cc; outline-offset:-3px; }} summary span {{ float:right; color:var(--muted); font:12px ui-monospace,Consolas,monospace; font-weight:400; }} .detail-body {{ border-top:1px solid var(--line); padding:20px; content-visibility:auto; }}
.source {{ color:var(--muted); font-size:13px; }} footer {{ color:var(--muted); text-align:center; font-size:13px; padding:8px; }}
@media (max-width:860px) {{ .page {{ padding:0 0 42px; }} .masthead,section {{ padding:24px 20px; }} .layout {{ display:block; margin-top:0; }} .toc {{ position:static; display:flex; overflow-x:auto; gap:4px; border-width:0 0 1px; padding:10px 16px; white-space:nowrap; }} .toc p {{ display:none; }} .toc a {{ display:inline-block; }} .facts,.decision-grid {{ grid-template-columns:1fr; }} summary span {{ display:none; }} }}
@media print {{ body {{ background:#fff; font-size:11pt; }} .page {{ max-width:none; padding:0; }} .toc,.skip-link {{ display:none; }} .masthead,section {{ box-shadow:none; break-inside:avoid; }} details {{ border:0; }} details[open] summary {{ display:none; }} .detail-body {{ display:none; }} }}
</style></head><body><a class="skip-link" href="#report-main">본문으로 건너뛰기</a><div class="page">
<header class="masthead"><p class="kicker">국가연구개발사업 심의결과 보고서</p><h1>{escape(project_name)}</h1><p class="subtitle">신규사업 심의 시뮬레이션 결과 · 의사결정용 요약본</p><div class="meta"><span><strong>심의 기준연도</strong> {review_year}</span><span><strong>수행 모델</strong> {provider} / {deep_model}</span><span><strong>실행 ID</strong> {execution_id}</span></div></header>
<div class="layout"><nav class="toc" aria-label="보고서 목차"><p>목차</p><a href="#decision">심의 의결</a><a href="#overview">사업 개요</a><a href="#issues">핵심 쟁점</a><a href="#conditions">이행 조건</a><a href="#questions">질의 대비</a><a href="#appendix">상세 검토자료</a></nav><main class="content" id="report-main">
<section class="decision" id="decision"><h2>1. 심의 의결</h2><div class="decision-grid"><div class="verdict"><span>최종 의결</span><strong>{_inline_html(decision)}</strong></div><div><p class="decision-summary">{_inline_html(summary)}</p><div class="notice"><strong>예산 판단</strong><br>{_inline_html(approved_budget)}</div><div class="notice"><strong>생성물 근거 검증</strong><br>{_inline_html(validation_status)} · 상세 내용은 부록의 생성물 근거 검증을 확인하세요.</div></div></div></section>
<section id="overview"><h2>2. 사업 개요</h2><dl class="facts"><div class="fact"><dt>사업명</dt><dd>{_inline_html(project_name)}</dd></div><div class="fact"><dt>심의 기준연도</dt><dd>{review_year}년</dd></div><div class="fact"><dt>예산 판단</dt><dd>{_inline_html(approved_budget)}</dd></div></dl><h3>입력 자료</h3><div class="source">{_markdown_to_html(source_manifest)}</div></section>
<section id="issues"><h2>3. 핵심 심의 쟁점 및 보완 요구</h2>{_markdown_to_html(documents.get("08_보완권고.md", "내용이 없습니다."))}</section>
<section id="conditions"><h2>4. 조건부 승인 이행 조건</h2>{_markdown_to_html(final.split("**이행 조건**:", 1)[1].strip() if "**이행 조건**:" in final else final)}</section>
<section id="questions"><h2>5. 예상 질의 및 답변 준비</h2>{_markdown_to_html(documents.get("07_예상질의응답.md", "내용이 없습니다."))}</section>
<section id="appendix"><h2>6. 상세 검토자료</h2><p class="source">아래 자료는 원본 Markdown의 표현기호를 제거해 읽기용으로 변환했습니다. 의결의 근거·추적이 필요할 때만 펼쳐 보세요.</p>{"".join(appendix_items)}</section>
</main></div><footer>본 문서는 심의 시뮬레이션 결과를 가독성 있게 정리한 보고서입니다. 사실관계와 예산 단위는 원본 기획보고서 및 근거자료로 최종 확인해야 합니다.</footer></div></body></html>"""
    report_path = out_dir / "심의종합리포트.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path


def save_results(final_state: dict, results_dir: str, project_id: str) -> Path:
    """심의 전 과정을 마크다운 파일로 저장하고 저장 디렉터리 경로를 반환."""
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}-{uuid4().hex[:8]}"
    out_dir = Path(results_dir) / project_id / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(filename: str, content: str) -> None:
        (out_dir / filename).write_text(content or "(내용 없음)", encoding="utf-8")

    write("00_입력문서_출처.md", final_state.get("source_manifest", ""))

    for key, filename in _ANALYST_FILES:
        write(filename, final_state.get(key, ""))

    write("02_심사공방_전문.md", final_state.get("review_debate_state", {}).get("history", ""))
    write(
        "03_전문위원회_의견.md",
        _render_json_field(final_state.get("review_plan", ""), ReviewPlan, render_review_plan),
    )
    write(
        "04_예산조정안.md",
        _render_json_field(
            final_state.get("budget_coordination_plan", ""), BudgetProposal, render_budget_proposal
        ),
    )
    write("05_재정검토토론_전문.md", final_state.get("audit_debate_state", {}).get("history", ""))
    write(
        "06_최종결정.md",
        _render_json_field(
            final_state.get("final_review_decision", ""), FinalDecision, render_final_decision
        ),
    )
    write("07_예상질의응답.md", final_state.get("anticipated_questions_md", ""))
    write("07b_예상질의.json", final_state.get("preparation_report_json", ""))
    write("08_보완권고.md", final_state.get("improvement_recommendations_md", ""))
    write("09_정량평가표.md", final_state.get("quality_scorecard_md", ""))
    write("10_불확실성_반대근거.md", final_state.get("uncertainty_report_md", ""))
    write("11_재심의_전후비교.md", final_state.get("rereview_comparison_md", ""))

    metadata = final_state.get("execution_metadata", {})
    metrics = final_state.get("execution_metrics", [])
    total_seconds = sum(item.get("elapsed_seconds", 0) for item in metrics)
    total_tokens = sum(item.get("total_tokens", 0) for item in metrics)
    observation = [
        "# 실행 관측성",
        "",
        f"- **실행 ID**: {metadata.get('execution_id', '알 수 없음')}",
        f"- **프로바이더**: {metadata.get('provider', '알 수 없음')}",
        f"- **Deep 모델**: {metadata.get('deep_model', '알 수 없음')}",
        f"- **Quick 모델**: {metadata.get('quick_model', '알 수 없음')}",
        f"- **체크포인트**: {'활성' if metadata.get('checkpoint_enabled') else '비활성'}",
        f"- **노드 누적시간**: {total_seconds:.4f}초",
        f"- **보고된 총 토큰**: {total_tokens:,}",
        "- **비용**: 모델별·시점별 가격표를 설정하지 않아 계산하지 않음",
        "",
        "| 노드 | 모델 | 시간(초) | 입력 토큰 | 출력 토큰 | 총 토큰 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in metrics:
        observation.append(
            f"| {item.get('node')} | {item.get('model')} | "
            f"{item.get('elapsed_seconds', 0):.4f} | {item.get('input_tokens', 0)} | "
            f"{item.get('output_tokens', 0)} | {item.get('total_tokens', 0)} |"
        )
    by_node = {}
    for item in metrics:
        node = item.get("node", "알 수 없음")
        aggregate = by_node.setdefault(node, {"calls": 0, "seconds": 0.0, "tokens": 0})
        aggregate["calls"] += 1
        aggregate["seconds"] += item.get("elapsed_seconds", 0) or 0
        aggregate["tokens"] += item.get("total_tokens", 0) or 0
    observation.extend(["", "## 노드별 합계", "", "| 노드 | 호출 수 | 누적 시간(초) | 총 토큰 |", "|---|---:|---:|---:|"])
    for node, aggregate in sorted(by_node.items(), key=lambda item: item[1]["seconds"], reverse=True):
        observation.append(
            f"| {node} | {aggregate['calls']} | {aggregate['seconds']:.4f} | {aggregate['tokens']:,} |"
        )
    bottlenecks = sorted(metrics, key=lambda item: item.get("elapsed_seconds", 0), reverse=True)[:3]
    observation.extend(["", "## 병목 후보 (단일 호출 상위 3건)", ""])
    observation.extend(
        f"- {item.get('node')}: {item.get('elapsed_seconds', 0):.4f}초 / {item.get('total_tokens', 0):,}토큰"
        for item in bottlenecks
    )
    write("12_실행관측성.md", "\n".join(observation))
    documents_for_validation = {
        filename: (out_dir / filename).read_text(encoding="utf-8")
        for filename, _ in _REPORT_FILES
        if (out_dir / filename).exists()
    }
    write("14_검증보고서.md", build_validation_report(documents_for_validation))
    _write_html_report(out_dir, project_id, metadata)

    return out_dir
