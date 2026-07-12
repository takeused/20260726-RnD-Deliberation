# RDAgents 보완 작업 컨텍스트 노트

작업 시작: 2026-07-12. 프로젝트 용도: 실제 R&D 예산 심의 전에 기획보고서 문제점 보완 + 예상 질의 파악.

## 배경 진단 (2026-07-12 검토 결과)

- TradingAgents 개조 프로젝트. 그래프 골격은 정상이나 한 번도 끝까지 실행된 적 없음.
- 실행 차단 버그 3건 확인: `get_client()` 미존재, `bind_structured` 인자 누락, stream values 모드 파싱 오류.
- 토론 count 버그: Pro/Aggressive/Conservative가 count를 안 올려 라운드 수가 설정의 2배 안팎으로 돌아감.
- 최종 산출물이 콘솔 3줄뿐 — 중간 보고서·토론 전문이 휘발됨. 예상 질의 생성 노드 자체가 없음.

## 결정 사항

### 심의기준 (사용자 지정)
- 최우선 평가 항목: **① 정부지원 필요성 ② 기술개발의 중요성 ③ 시급성**.
- 공통 심의기준 블록을 `rdagents/agents/utils/review_criteria.py`에 단일 정의하고 분석가·토론자·위원장·질의추출기 프롬프트에 공통 주입한다. 프롬프트마다 복붙하지 않는 이유: 기준 개정 시 한 곳만 고치면 되게.

### 1단계 관련
- 프로바이더별 effort 인자명이 달라(google=thinking_level, openai/azure=reasoning_effort, anthropic=effort) `review_graph`에서 매핑 후 전달. None 값은 아예 전달하지 않음(GoogleClient가 `key in kwargs`로 검사하므로 None을 넘기면 temperature=None이 그대로 들어가는 문제).
- stream은 `values` 모드 유지, `final_state = s`(청크 자체가 전체 상태). 진행 표시는 마지막 메시지의 name으로 대체.
- 기본 모델: 카탈로그(`model_catalog.py`)에 gemini-2.5 계열이 없어 경고 발생 → gemini-3.1-pro-preview / gemini-3.5-flash로 변경.
- `bind_structured`가 None(미지원 프로바이더)일 때: 자유 텍스트로 폴백하고 텍스트를 스키마의 rationale 계열 필드에 담는다. 파이프라인이 중단되지 않는 것이 우선.

### 2단계 관련
- 예상 질의는 Con Reviewer·재정 검토 토론에서 이미 나온 공격 논리를 원석으로 삼아 별도 추출 노드(deep_llm)가 구조화한다. 질의마다 심의기준 태그(정부지원 필요성/중요성/시급성/기타)를 붙여 사용자가 우선순위를 알 수 있게.
- 저장 구조: `~/.rdagents/logs/{project_id}/{YYYYMMDD_HHMMSS}/` 아래 번호 접두사 md 파일. 과정 기록이 본체이므로 전부 저장.

### 3단계 관련
- HWP 직접 파싱은 범위 제외. 원문 모드는 .md/.txt만 지원 — HWP는 사용자가 기존 hwp 변환 도구로 md 변환 후 투입하는 흐름. 이유: HWP 파서 의존성 추가는 과잉이고, 이 환경에 변환 스킬이 이미 있음.
- 원문 모드는 줄 번호 보존 청크 인덱스를 만들고 7개 조회 도구가 분석 관점별 관련 청크만 반환한다. 각 청크는 출처 줄 번호와 `<untrusted_document>` 신뢰 경계를 포함한다.
- `_project_cache` 제거: 보고서 수정 → 재심의 루프를 막는 원인. 파일이 작아 매번 재로드해도 비용 없음.

### 4단계 관련
- 웹 검색 도구 연동은 이번 범위에서 제외. 이유: 의존성·API 키 추가 대비, 사용자 목적(자기 보고서 취약점 발견)에는 내부 논증 검증이 우선. 필요 시 후속 작업.
- output_language 설정 미배선은 알려진 한계로 남김(전 에이전트에 config 배관 추가는 과잉). 한국어 고정.
- 심의 이력: 실행마다 요약 1건을 `memory_log_path`(md)에 append, 같은 project_id 재심의 시 해당 항목들을 `past_context`로 로드해 Review Manager·Final Approver 프롬프트에 주입. 보완 전후 비교가 목적.

## 작업 완료 기록 (2026-07-12)

- 1~4단계 전부 구현 완료. 오프라인 스모크 테스트 2종(`tests/test_smoke.py`) 통과.
  - 전체 파이프라인: 분석 6건 → 찬반 4발언 → 위원장 → 조정관 → 3자 3발언 → 최종결정 → 질의추출 → 독립 품질평가 → 재심의 비교 → 파일 18개 저장.
  - 원문 모드 + 재심의: 1차 past_context 빈 값, 2차 주입 확인. 원문 모드 도구의 관련 청크·줄 번호 출처·신뢰 경계 확인.
- 추가로 고친 것: `_clear_messages`가 `{"messages": []}` 반환 → add_messages 리듀서에서 no-op이라 실제로 안 지워지던 버그. RemoveMessage + placeholder HumanMessage로 교체 (TradingAgents 원본 방식).
- 실제 LLM 실행은 .env 미존재로 미수행. pytest 미설치 — 테스트는 `python tests/test_smoke.py` 직접 실행.
- 알려진 한계: output_language 설정 미배선(한국어 고정), 웹/API 자동 근거 수집 미연동, 모델 가격표 미설정으로 비용 미계산, structured.py의 TradingAgents 잔재 docstring.

## 검증 전략

- API 키 없이도 전체 그래프를 돌릴 수 있게 가짜 LLM 스텁(`tests/test_smoke.py`)으로 검증: 노드 발화 횟수, 토론 종료 조건, 파일 생성.
- .env 미존재 확인(2026-07-12). 실제 LLM 실행은 사용자가 키 설정 후 가능.

## 6단계 작업 기록 (2026-07-12 3차 세션)

재검토에서 발견한 문제를 우선순위대로 처리. 설계 결정과 이유.

- **구조화 재시도를 include_raw=True 경로로 구현한 이유**: 파싱/검증 오류가 예외 대신 dict의
  parsing_error로 돌아와 재시도 판단이 안전하고, raw 메시지에서 usage_metadata도 함께 얻는다.
  include_raw 미지원 프로바이더(TypeError)는 기존 경로로 자동 폴백.
- **폴백 verdict를 '보류' 유지한 이유**: verdict는 Enum이라 '판정불능' 값 추가는 스키마 오염.
  대신 요약·근거에 "구조화 출력 실패" 마커를 남기고, 메모리 기록에서 제외하는 쪽을 선택.
- **재개 조건을 '사용자가 execution_id를 명시한 경우'로 한정**: 자동 생성 ID는 매 실행 고유하므로
  재개 대상이 없음. snapshot.next가 비어 있으면(완주) 새 실행으로 처음부터 진행.
- **FakeLLM이 include_raw를 지원하도록 확장**: 구조화 노드의 usage 전파를 오프라인에서 검증하기 위해
  스텁이 {"raw": usage 포함 AIMessage, "parsed": 모델} 형태를 반환. run_smoke가 토큰 합>0 을 단언.
- pytest 9종 통과. ruff는 미설치로 미실행 (dev extras에는 선언돼 있음).
- 실제 LLM 실행은 여전히 차단 (.env 없음). GOOGLE_API_KEY 설정 후
  `python main.py --project quantum_computing --debug` 1회가 남은 마지막 검증.
