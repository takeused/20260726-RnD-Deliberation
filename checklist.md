# RDAgents 보완 작업 체크리스트

목표: 실행 불가 상태의 심의 시뮬레이터를 "기획보고서 보완점 도출 + 예상 질의 파악" 도구로 완성한다.
핵심 심의기준: **정부지원 필요성, 기술개발의 중요성 및 시급성** (사용자 지정 최우선 항목).

## 1단계 — 실행 가능화 (버그 수정)

- [x] `review_graph.py`: `.get_client()` → `.get_llm()` 수정
- [x] `review_graph.py`: `backend_url` → 팩토리 인자명 `base_url`로 전달
- [x] `review_graph.py`: 프로바이더별 effort 인자명 매핑 (google=`thinking_level`, openai/azure=`reasoning_effort`, anthropic=`effort`), None 값은 전달 생략
- [x] `review_graph.py`: `stream_mode="values"`에 맞게 최종 상태 파싱 수정
- [x] `review_manager.py` / `budget_coordinator.py` / `final_approver.py`: `bind_structured`에 `agent_name` 인자 추가, `None` 반환(미지원 프로바이더) 시 폴백 처리
- [x] `pro_reviewer.py`: 토론 count 증가 추가
- [x] `aggressive_auditor.py` / `conservative_auditor.py`: count 증가 추가
- [x] `default_config.py` / `.env.example` / `README.md`: 기본 모델을 카탈로그 기준 현행 모델(gemini-3.1-pro-preview / gemini-3.5-flash)로 갱신
- [x] 검증: 가짜 LLM(오프라인 스텁)으로 전체 그래프 실행 → 모든 노드 발화 횟수·종료 조건 확인

## 2단계 — 산출물 재설계 (목적 정합화)

- [x] 예상 질의 추출 스키마 정의 (`schemas.py`: 질의·근거·권장답변·심의기준 분류 / 취약점·심각도·보완방향)
- [x] `question_extractor.py` 노드 신설 (deep_llm, 전체 심의 이력 입력)
- [x] 그래프 연결: Final Approver → Question Extractor → END, 상태 필드 추가
- [x] 결과 저장기 신설: `results_dir/{project}/{timestamp}/`에 분석보고서 6건·토론 전문·최종결정·예상질의응답.md·보완권고.md 저장
- [x] `main.py`: 저장 경로 안내 출력
- [x] 검증: 가짜 LLM 실행 후 파일 생성 확인

## 3단계 — 입력 현실화

- [x] `--report <path>` 옵션: 기획보고서 원문(.md/.txt) 직접 입력 모드
- [x] 원문 모드에서 줄 번호 보존 청킹·관점별 검색·출처 표기를 제공하도록 `project_loader.py` 확장
- [x] 원문 내부 명령을 신뢰하지 않는 `<untrusted_document>` 경계와 입력 크기·확장자 제한
- [x] 독립 외부 근거 파일 다중 입력 및 사업보고서/외부근거 유형 구분
- [x] 고정 가중치 기반 정량 평가표와 불확실성·반대 근거 보고서 생성
- [x] 재심의 전후 해소·미해소·신규 지적사항 비교 보고서
- [x] SQLite 체크포인트와 실행 ID 배선
- [x] 노드별 실행시간·모델·토큰 관측성 보고서
- [x] 프로젝트 캐시 제거(수정본 재심의 가능하게 매번 재로드)
- [x] 검증: 원문 모드 가짜 LLM 실행

## 4단계 — 심의 리얼리즘

- [x] `review_criteria.py`: 심의기준 텍스트 정의 — ① 정부지원 필요성 ② 기술개발의 중요성 ③ 시급성 + 보조 기준
- [x] 6인 분석가 + Pro/Con + Review Manager + Question Extractor 프롬프트에 심의기준 주입
- [x] 심의 이력 메모리: 실행 결과 요약을 `memory_log_path`에 누적, 동일 사업 재심의 시 `past_context`로 로드
- [x] 검증: 재실행 시 이전 이력이 프롬프트에 반영되는지 확인

## 최종 검증

- [x] 오프라인 스모크 테스트 전체 통과
- [ ] (API 키 보유 시) 실제 LLM으로 축소 실행 1회 — .env 미존재로 계속 보류 (6단계까지 완료된 코드 기준)

## 6단계 — 재검토 후속 조치 (2026-07-12)

- [x] 구조화 출력 재시도 (검증 오류 피드백, include_raw 경로)
- [x] usage_metadata 보존 → 토큰 관측성 복구 (11개 노드)
- [x] 체크포인트 중단 지점 재개 실구현 + 크래시-재개 테스트
- [x] search_report 검색 도구 (6인 분석가 공통)
- [x] 예상 질의 최소 개수·3대 기준 커버리지 검증
- [x] 폴백 결정의 메모리 기록 제외
- [x] 가중치 단일 정의, 언어 지시 보강, sqlite close, 메모리 파싱 견고화
- [x] pytest 설치 + 데드 테스트 편입 + 신규 테스트 3종 → 전체 9종 통과

## 다음 작업 (백로그, 우선순위 순)

- [ ] **실제 LLM 실행 1회 (최우선)** — `.env`에 GOOGLE_API_KEY 설정 후
      `python main.py --project quantum_computing --debug`.
      확인 포인트: ① 구조화 재시도가 실전에서 작동하는지 ② 12_실행관측성.md 토큰이 0이 아닌지
      ③ 07_예상질의응답.md 질의 품질(3대 기준 커버리지)
- [ ] 실제 기획보고서(HWP→md 변환)로 원문 모드 실전 심의 1회 + 보완 후 재심의로 11_전후비교 확인
- [ ] NTIS·정책문서 등 웹 검색 교차 검증 연동 (현재는 --evidence 파일 수동 투입만 가능)
- [ ] HWP→md 변환 헬퍼 스크립트 통합 (현재 수동 변환 안내만)
- [ ] 모델 가격표 기반 비용 계산 (현재 '계산 안 함' 명시)
- [ ] 임베딩 기반 의미 검색 (현재 키워드 빈도 랭킹)
- [ ] output_language 설정 배선 (현재 한국어 고정)
- [ ] ruff 설치 후 린트 정리 (dev extras 선언만 된 상태)

## 7단계 — 원천 목표(예산 확보) 정렬 개조 (2026-07-12 승인)

- [ ] ① 사후 검증 루프: 예상 질의 JSON 저장(07b) + `--verify-questions`로 실제 질의 대조·적중률 기록
- [ ] ② 토론층 교체: Pro/Con → 심사위원 패널(공격) vs 사업 발표자(방어)
- [ ] ③ 모의 청문 모드: `--hearing`으로 예상 질의 대화형 리허설 + 답변 평가·압박 후속질의
- [ ] ④ 관문 프로파일(--gate: 부처심의/예타/예산조정/국회) + 질의 은행(전형 패턴 시드, 검증된 실제 질의 자동 축적)
