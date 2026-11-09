import argparse
import json
import os
import sys

from dotenv import load_dotenv

try:
    # 회사 프록시처럼 TLS를 가로채는 환경에서는 Python 기본 인증서 묶음이 프록시 인증서를 몰라
    # LLM API 호출이 "Connection error"로 실패한다. 운영체제 인증서 저장소를 쓰게 한다.
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # 선택 의존성: 없으면 기본 인증서 묶음 사용
    pass

from rdagents.default_config import _ENV_OVERRIDES
from rdagents.graph.review_graph import HUMAN_REVIEW_PENDING, RDReviewGraph
from rdagents.dataflows.issue_ledger import needs_human_review  # noqa: E402 (rdagents.agents를 먼저 불러야 순환 import가 없음)
from rdagents.llm_clients.api_key_env import get_api_key_env
from rdagents.llm_clients.quota import DailyQuotaExceeded, RequestTooLarge


_KEY_OPTIONAL_PROVIDERS = {"bedrock", "ollama", "openai_compatible"}

# 실행 프로파일: 테스트는 저비용(Groq/로컬), 실전은 Gemini
PROFILES = {
    # Groq 무료 등급은 분당 8,000토큰이라 요청 하나가 그보다 크면 거절된다 -> 짧은 문맥 예산
    "test-groq": {
        "llm_provider": "groq",
        "deep_think_llm": "openai/gpt-oss-120b",
        "quick_think_llm": "openai/gpt-oss-120b",
        # 1200이면 예상 질의 단계 요청이 분당 한도에 닿음 (NDMI 실행, 413). 실행 도중 수치 표시가 붙은 뒤로는
        # 900에서도 8,120토큰으로 넘쳤음 (groq6)
        "prompt_char_budget": 800,
        # 쟁점별 공방: 쟁점 하나에 짧은 요청 2건. 분야 기술전문가 노드가 더해져 NDMI 추정 18.2만 토큰(하루 한도의
        # 91%)이라 4개로 (반드시 올릴 쟁점이 많으면 6개까지 늘어남)
        "max_debate_issues": 4,
        # 분석가가 도구 3개(개요·기술·검색)를 부르면 결과가 한 요청에 쌓인다. 1500자 조각이면 8,555토큰으로
        # 분당 한도(8,000)를 넘었음(NDMI 실행, 413) -> 900자
        "report_chunk_chars": 900,
        "report_retrieval_top_k": 2,
        # 조각을 줄여도 도구를 4번 부르면 다시 넘었음 -> 도구 결과 총량에 예산 (약 2,500토큰)
        "tool_result_char_budget": 3500,
        # 분석가 3명에 약 9만 토큰이 들어 하루 한도(20만)로 심의를 끝낼 수 없었음 -> 도구 호출 3번까지
        "max_analyst_tool_calls": 3,
        # gpt-oss는 추론 토큰도 출력 상한(Groq 기본 3,072)을 쓴다. NDMI 실행에서 응답 5건이 상한에서 잘렸고
        # 예상 질의 JSON이 완성되지 못했음 -> 추론을 줄여 본문에 출력을 남긴다
        "openai_reasoning_effort": "low",
    },
    "test-local": {
        "llm_provider": "ollama",
        "deep_think_llm": "gemma4:e4b",
        "quick_think_llm": "gemma4:e4b",
        "prompt_char_budget": 6000,
    },
    "prod": {
        "llm_provider": "google",
        "deep_think_llm": "gemini-3.1-flash",
        "quick_think_llm": "gemini-3.1-flash",
    },
}


def _validate_provider_auth(provider: str) -> str | None:
    """선택한 프로바이더에 필요한 인증 환경변수의 오류 메시지를 반환한다."""
    provider = provider.lower()
    if provider in _KEY_OPTIONAL_PROVIDERS:
        return None
    env_var = get_api_key_env(provider)
    if env_var is None:
        return f"지원 여부를 확인할 수 없는 LLM 프로바이더입니다: {provider}"
    if not os.getenv(env_var):
        return f"{provider} 프로바이더에 필요한 {env_var}가 설정되어 있지 않습니다."
    return None


def _human_reviewer(answers_path: str | None):
    """사람 검토 노드가 멈췄을 때 판단을 받는 함수: 답 파일이 있으면 그걸 쓰고, 터미널이면 묻고, 둘 다 아니면 None(멈춤)."""
    if answers_path:
        with open(answers_path, encoding="utf-8") as f:
            answers = json.load(f)
        return lambda payload: answers
    if not sys.stdin.isatty():
        return None

    def ask(payload: dict) -> dict:
        print("\n" + "=" * 60 + "\n사람 검토: 공방 전에 판단이 필요한 쟁점\n" + payload["guide"] + "\n" + "=" * 60)
        decisions = {}
        for item in payload["issues"]:
            print(f"\n#{item['id']} [{item['criterion']}·{item['severity']}] {item['issue']}")
            print(f"   출처: {item['origin']} ({item['verify_note']})")
            choice = input("   상정(s) / 제외(x) / 코드 규칙대로(Enter): ").strip().lower()
            decision = {"s": "상정", "상정": "상정", "x": "제외", "제외": "제외"}.get(choice)
            if decision:
                decisions[str(item["id"])] = {"decision": decision, "note": input("   메모(선택): ").strip()}
        return decisions

    return ask


def main():
    parser = argparse.ArgumentParser(description="R&D 신규사업 예산 심의 시뮬레이터")
    parser.add_argument(
        "--project",
        type=str,
        default="quantum_computing",
        help="심의 대상 사업 ID (예: quantum_computing, bio_health)",
    )
    parser.add_argument(
        "--report-project-id",
        type=str,
        default=None,
        help="원문 보고서의 안정적인 사업 ID. 미지정 시 파일 경로 기반 ID를 생성합니다.",
    )
    parser.add_argument(
        "--verify-questions",
        type=str,
        default=None,
        help="실제 심의에서 받은 질의 파일(.md/.txt). --run-dir의 예측과 대조해 적중률을 기록합니다.",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="심의 실행 결과 디렉터리 (--verify-questions 또는 --hearing과 함께 사용).",
    )
    parser.add_argument(
        "--hearing",
        action="store_true",
        help="모의 청문 모드: --run-dir의 예상 질의로 대화형 답변 리허설을 진행합니다.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=None,
        help="실행 프로파일: test-groq(Groq API), test-local(Ollama gemma4:e4b), "
             "prod(Gemini 3.1 Flash). 미지정 시 .env/기본 설정 사용.",
    )
    parser.add_argument(
        "--gate",
        choices=["부처심의", "예타", "예산조정", "국회"],
        default=None,
        help="대비할 심의 관문. 관문별로 심사위원 성향과 질의 각도가 달라집니다. (기본: 부처심의)",
    )
    parser.add_argument(
        "--project-type",
        choices=["auto", "산업형", "공공임무형", "혼합형"],
        default=None,
        help="사업 유형. 심의기준·정량 평가 가중치·사전 점검 항목·필수 질의가 유형에 따라 달라집니다. "
             "(기본: auto, 원문 키워드로 판별)",
    )
    parser.add_argument(
        "--human-review",
        action="store_true",
        help="쟁점 등록 뒤 정책 판단이 필요한 '상' 쟁점(정부지원 필요성·정책·규제, 출처 미확인)을 공방 전에 사람에게 묻습니다. "
             "터미널이면 바로 묻고, 아니면 멈춘 뒤 --execution-id와 --human-answers로 이어 갑니다.",
    )
    parser.add_argument(
        "--human-answers",
        default=None,
        help="사람 검토 답 JSON 파일. 예: {\"1\": \"상정\", \"9\": {\"decision\": \"제외\", \"note\": \"부처 협의 사항\"}}",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="독립 교차검증 근거 파일(.md/.txt). 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument(
        "--execution-id",
        default=None,
        help="체크포인트 실행 ID. 같은 ID를 지정하면 동일 실행 이력을 이어서 사용합니다.",
    )
    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="기획보고서 원문 파일 경로 (.md/.txt). 지정 시 --project보다 우선. "
             "HWP는 md로 변환 후 투입하세요.",
    )
    parser.add_argument(
        "--year",
        type=str,
        default="2027",
        help="심의 대상 연도",
    )
    parser.add_argument(
        "--rerender",
        action="store_true",
        help="LLM 없이 --run-dir의 저장된 산출물로 검증보고서(14)·원문에 없는 수치 표시·HTML 리포트를 지금 코드로 "
             "다시 만듭니다. 입력 원문(--report, --evidence)이 필요합니다.",
    )
    parser.add_argument(
        "--compare-runs",
        nargs=2,
        metavar=("RUN_DIR_A", "RUN_DIR_B"),
        default=None,
        help="두 실행 결과 폴더를 같은 지표(잘린 응답·인용·원문에 없는 수치·예상 질의·토큰)로 비교합니다.",
    )
    parser.add_argument(
        "--estimate-tokens",
        action="store_true",
        help="LLM을 부르지 않고 노드별 요청 크기와 총 토큰을 추정합니다 (분당·하루 한도 확인). "
             "--execution-id를 주면 체크포인트에서 이어서 실행할 남은 부분만 셉니다.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="디버그 출력 활성화",
    )
    args = parser.parse_args()

    # 환경변수 강제 로드
    load_dotenv(override=True)

    # 프로파일·관문 오버라이드 (모든 실행 모드에 공통 적용)
    overrides = dict(PROFILES[args.profile]) if args.profile else {}
    # 사용자가 RDAGENTS_* 환경변수로 직접 준 값은 프로파일보다 우선 (예: 요청이 크면 조각 크기만 줄여 재실행)
    for env_var, key in _ENV_OVERRIDES.items():
        if os.environ.get(env_var):
            overrides.pop(key, None)
    if args.gate:
        overrides["review_gate"] = args.gate
    if args.project_type:
        overrides["project_type"] = args.project_type
    if args.human_review or args.human_answers:
        overrides["human_review"] = True
    overrides = overrides or None

    provider = (
        overrides["llm_provider"] if overrides and "llm_provider" in overrides
        else os.getenv("RDAGENTS_LLM_PROVIDER", "groq")
    )
    # 결과 비교·다시 만들기 모드: LLM 호출 없음
    if args.compare_runs:
        from rdagents.dataflows.run_compare import render as render_comparison

        print(render_comparison(*args.compare_runs))
        return 0
    if args.rerender:
        if not args.run_dir or not args.report:
            print("오류: --rerender에는 --run-dir과 --report(그 실행의 입력 원문)가 필요합니다.", file=sys.stderr)
            return 2
        from rdagents.dataflows.project_loader import set_current_report
        from rdagents.dataflows.result_writer import rerender_results

        set_current_report(args.report, args.report_project_id, evidence_paths=args.evidence)
        out = rerender_results(args.run_dir, review_year=args.year)
        print(f"다시 만듦: {out / '14_검증보고서.md'}, {out / '심의종합리포트.html'}")
        return 0

    # 토큰 추정 모드: API 키 없이 가짜 LLM으로 요청 크기만 센다
    if args.estimate_tokens:
        from rdagents.dataflows.token_estimate import estimate, render
        from rdagents.default_config import DEFAULT_CONFIG

        config = {**DEFAULT_CONFIG, **(overrides or {})}
        est = estimate(config, dict(
            project_id=args.project, review_year=args.year, report_path=args.report,
            report_project_id=args.report_project_id, evidence_paths=args.evidence,
        ), execution_id=args.execution_id)
        print(render(est, tpm=int(os.getenv("RDAGENTS_TPM_LIMIT", "8000")),
                     tpd=int(os.getenv("RDAGENTS_TPD_LIMIT", "200000"))))
        return 0

    auth_error = _validate_provider_auth(provider)
    if auth_error:
        print(f"오류: {auth_error}", file=sys.stderr)
        print(".env 파일을 확인해 주세요.", file=sys.stderr)
        return 2

    # 모의 청문 모드: 예상 질의로 대화형 리허설
    if args.hearing:
        if not args.run_dir:
            print("오류: --hearing에는 --run-dir이 필요합니다.", file=sys.stderr)
            return 2
        from rdagents.hearing import run_hearing

        graph = RDReviewGraph(config=overrides, debug=args.debug)
        try:
            run_hearing(graph.deep_llm, args.run_dir)
        except Exception as e:
            print(f"\n[청문 실패]: {e}", file=sys.stderr)
            return 1
        finally:
            graph.close()
        return 0

    # 사후 검증 모드: 시뮬레이션 없이 실제 질의 대조만 수행
    if args.verify_questions:
        if not args.run_dir:
            print("오류: --verify-questions에는 --run-dir이 필요합니다.", file=sys.stderr)
            return 2
        from rdagents.dataflows.question_verification import verify_questions

        graph = RDReviewGraph(config=overrides, debug=args.debug)
        try:
            with open(args.verify_questions, encoding="utf-8") as f:
                actual_text = f.read()
            _, stats = verify_questions(
                graph.deep_llm, args.run_dir, actual_text,
                graph.config["verification_history_path"],
                question_bank_dir=graph.config["question_bank_dir"],
            )
        except Exception as e:
            print(f"[검증 실패]: {e}", file=sys.stderr)
            return 1
        finally:
            graph.close()
        print("=" * 60)
        print(f"질의 적중 검증 완료: 실제 {stats['total']}건 중 "
              f"적중 {stats['hits']} / 부분 {stats['partials']} / 미적중 {stats['misses']}")
        print(f"가중 적중률: {stats['weighted_hit_rate']}%")
        print(f"상세 보고서: {args.run_dir} 의 13_질의적중검증.md")
        print(f"누적 이력: {graph.config['verification_history_path']}")
        return 0

    target = args.report if args.report else args.project
    print(f"[{args.year}년도 R&D 신규사업 예산 심의 시뮬레이션 시작: {target}]\n")
    print("그래프 초기화 중...")

    # 워크플로우 인스턴스화 (프로파일·관문 오버라이드 적용)
    graph = RDReviewGraph(config=overrides, debug=args.debug)

    # 실행
    print("심의 파이프라인 실행 중 (잠시만 기다려 주세요)...\n")
    try:
        final_state, decision = graph.propagate(
            project_id=args.project,
            review_year=args.year,
            report_path=args.report,
            report_project_id=args.report_project_id,
            evidence_paths=args.evidence,
            execution_id=args.execution_id,
            human_reviewer=_human_reviewer(args.human_answers),
        )
        if decision == HUMAN_REVIEW_PENDING:
            print("\n사람 검토를 기다리며 멈췄습니다. 위 쟁점 번호로 답 파일(JSON)을 만들어 같은 명령에 다음을 붙여 이어 가세요:")
            print("  --execution-id <위 실행 번호> --human-answers <답 파일>  (체크포인트가 켜져 있어야 합니다)")
            for item in (final_state.get("issue_ledger") or []):
                if needs_human_review(item):
                    print(f"  #{item['id']} [{item['criterion']}·{item['severity']}] {item['issue'][:80]}")
            return 0

        print("\n" + "=" * 60)
        print("최종 심의 결과")
        print("=" * 60)
        
        if decision:
            # JSON 렌더링
            try:
                decision_dict = json.loads(decision)
                print(f"결정: {decision_dict.get('verdict')}")
                print(f"예산: {decision_dict.get('approved_budget_billion')}억원")
                print(f"요약: {decision_dict.get('executive_summary')}")
            except Exception:
                print(decision)
        else:
            print("결과가 반환되지 않았습니다.")

        saved_dir = final_state.get("saved_results_dir")
        if saved_dir:
            print("\n" + "=" * 60)
            print(f"심의 전 과정이 저장되었습니다: {saved_dir}")
            print("- 07_예상질의응답.md : 심의위원 예상 질의 + 권장 답변 초안")
            print("- 08_보완권고.md     : 기획보고서 보완 권고")
            print("- 09_정량평가표.md   : 기준별 점수·신뢰도·근거")
            print("- 10_불확실성_반대근거.md : 불일치·반대 근거·추가 확인 자료")
            print("- 11_재심의_전후비교.md : 해소·미해소·신규 지적사항")
            print("- 12_실행관측성.md : 모델·노드 시간·토큰·비용 상태")
            print("- 심의종합리포트.html : 전체 결과 통합 열람용 리포트")
            
    except DailyQuotaExceeded as e:
        # 하루 한도는 재시도로 풀리지 않는다: 멈추고 이어서 실행하는 방법을 안내
        wait = f"약 {e.retry_after} 뒤" if e.retry_after else "한도가 풀린 뒤"
        print(f"\n[하루 사용량 한도 초과] {provider} 공급자의 하루 한도에 걸려 심의를 멈췄습니다.", file=sys.stderr)
        if args.execution_id and graph.config.get("checkpoint_enabled"):
            print(f"{wait} 같은 명령(--execution-id {args.execution_id})으로 다시 실행하면 "
                  "끝난 단계는 건너뛰고 이어서 진행합니다.", file=sys.stderr)
        else:
            print(f"{wait} 다시 실행하세요. 이어서 실행하려면 RDAGENTS_CHECKPOINT_ENABLED=true와 "
                  "--execution-id를 지정해야 합니다 (지금은 처음부터 다시 실행됨).", file=sys.stderr)
        print("안내된 대기 시간은 '다음 요청 하나'가 들어갈 자리가 생기는 시간입니다. 남은 심의 전체가 끝나려면 "
              "더 오래 기다려야 할 수 있습니다 (Groq 무료: 하루 20만 토큰, 심의 1회 약 11만 토큰).", file=sys.stderr)
        print(f"공급자 메시지: {e}", file=sys.stderr)
        return 3
    except RequestTooLarge as e:
        print(f"\n[요청 크기 초과] {provider} 공급자의 분당 토큰 한도보다 큰 요청이 만들어져 심의를 멈췄습니다.",
              file=sys.stderr)
        print("분석가 단계면 보고서 조각을 줄이세요. 예: RDAGENTS_REPORT_CHUNK_CHARS=600, RDAGENTS_REPORT_TOP_K=1. "
              "공방 이후 단계면 문맥 예산을 줄이세요. 예: RDAGENTS_PROMPT_CHAR_BUDGET=900. "
              "체크포인트를 켰다면 같은 --execution-id로 이어서 실행되고, 새로 준 환경변수가 적용됩니다. "
              "얼마나 줄일지는 --estimate-tokens로 먼저 확인하세요.", file=sys.stderr)
        print(f"공급자 메시지: {e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"\n[오류 발생]: {e}", file=sys.stderr)
        return 1
    finally:
        graph.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
