# 🗂️ 쟁점 등록 (Issue Registrar) — 분석 보고서의 지적을 쟁점 원장에 등록
"""분석가 9명(분야 기술전문가 3명 + 기능별 6명)의 보고서에서 심의 쟁점을 뽑아 원장에 올린다.
LLM은 쟁점과 출처를 옮겨 적기만 하고, 출처 검증·공방 순서·질의 위원 배정은 코드가 한다 (dataflows/issue_ledger.py).
사전 점검 누락·숫자 검산 불일치는 코드가 찾은 확정 문제라 LLM을 거치지 않고 원장 앞에 둔다.
"""

from langchain_core.prompts import ChatPromptTemplate

from rdagents.agents.schemas import IssueRegister
from rdagents.agents.utils.agent_utils import clip_text, make_ai_message
from rdagents.agents.utils.structured import invoke_structured_model
from rdagents.dataflows.issue_ledger import build_ledger, render_ledger

REPORT_SECTIONS = [
    ("domain_expert_report", "분야 기술전문가 검토"),
    ("tech_value_report", "기술 가치 분석"),
    ("tech_trend_report", "기술 트렌드/중복성 분석"),
    ("economic_report", "경제/재무 타당성 분석"),
    ("policy_report", "정책 부합성 분석"),
    ("feasibility_report", "수행체계 분석"),
    ("regulatory_report", "규제/윤리 검토"),
]


def create_issue_registrar(llm):
    def issue_registrar_node(state):
        project_type = state.get("project_type") or "혼합형"
        criteria = "정부지원 필요성, 기술개발의 중요성, 시급성, 예산 타당성, 기타" + (
            ", 현장 적용·확산" if project_type in ("공공임무형", "혼합형") else "")
        system = (
            "당신은 R&D 예산 심의의 간사입니다. 아래 분석 보고서들에서 심의 공방에서 다룰 쟁점을 5~10개 뽑아 원장에 등록하세요.\n"
            f"- 사업 유형: {project_type}. 심의기준은 {criteria} 중 하나로 분류하세요.\n"
            "- 쟁점은 '무엇이 부족하거나 의심스러운가'를 한 문장으로. 보고서의 칭찬·요약은 쟁점이 아닙니다.\n"
            "- cite에는 분석 보고서가 그 지적에 단 [출처: 파일명 L시작-L끝]을 그대로 옮기고, quote에는 그 줄에 실제로 있는 "
            "원문 구절을 그대로 복사하세요. 출처가 없는 지적은 cite와 quote를 비워 두세요 (지어내면 코드 검증에서 걸립니다).\n"
            "- 보고서에 없는 수치·사실을 쟁점에 새로 쓰지 마세요."
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "## 분석 보고서\n\n{reports}\n\n심각도 높은 순으로 쟁점을 등록하세요."),
        ])
        # 보고서마다 따로 줄인다 (한꺼번에 줄이면 앞 보고서만 남음). 줄일 때 끝의 요약 표가 남도록 앞뒤를 보존
        reports = "\n\n".join(
            f"--- {name} ---\n{clip_text(state[key], state, fraction=0.6)}"
            for key, name in REPORT_SECTIONS if state.get(key)
        )
        prompt_val = prompt.invoke({"reports": reports or "분석 보고서 없음"})
        call = invoke_structured_model(llm, IssueRegister, prompt_val, "Issue Registrar")
        registered = [i.model_dump(mode="json") for i in call.model.issues] if call.model else []
        ledger = build_ledger(registered, state.get("precheck_issues") or [], project_type)
        return {
            "messages": [make_ai_message(render_ledger(ledger), "IssueRegistrar", call.usage)],
            "issue_ledger": ledger,
        }

    return issue_registrar_node
