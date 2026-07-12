import argparse
import json
import os
import sys

from dotenv import load_dotenv

from rdagents.graph.review_graph import RDReviewGraph
from rdagents.llm_clients.api_key_env import get_api_key_env


_KEY_OPTIONAL_PROVIDERS = {"bedrock", "ollama", "openai_compatible"}


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
        "--debug",
        action="store_true",
        help="디버그 출력 활성화",
    )
    args = parser.parse_args()

    # 환경변수 강제 로드
    load_dotenv(override=True)

    provider = os.getenv("RDAGENTS_LLM_PROVIDER", "google")
    auth_error = _validate_provider_auth(provider)
    if auth_error:
        print(f"오류: {auth_error}", file=sys.stderr)
        print(".env 파일을 확인해 주세요.", file=sys.stderr)
        return 2

    target = args.report if args.report else args.project
    print(f"[{args.year}년도 R&D 신규사업 예산 심의 시뮬레이션 시작: {target}]\n")
    print("그래프 초기화 중...")

    # 워크플로우 인스턴스화
    graph = RDReviewGraph(debug=args.debug)

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
        )
        
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
            
    except Exception as e:
        print(f"\n[오류 발생]: {e}", file=sys.stderr)
        return 1
    finally:
        graph.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
