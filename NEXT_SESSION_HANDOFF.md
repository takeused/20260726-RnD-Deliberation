# 다음 작업 재개 인수인계

작성일: 2026-07-26

## 현재 상태

- 신뢰성 보완 코드와 테스트는 완료되었다. `tests/test_smoke.py`는 14건 통과했고, `compileall` 검사도 통과했다.
- 기존 실제 실행 결과는 보존한다.
  - `results/institutional-outcomes-civil-convergence-2027/20260726_081334_089199-fd972943/`
- 새 Cerebras 실행은 두 차례 시작했으나, 결과 저장 전 사용자 요청으로 중단했다. 현재 실행 중인 Python/Cerebras 프로세스는 없다.
- 첫 재실행은 전체 문맥 기본 설정으로 10분 제한에 도달했다. 두 번째 재실행은 `test-cerebras` 프로필로 전환했고, 문서 조회 단계(`get_project_overview`, `get_tech_details`, `search_report`, `get_similar_projects`, `get_budget_details`)까지 진행한 뒤 중단했다. 중간 결과는 저장되지 않는다.

## 재개 전 확인

1. 작업 폴더에서 `.env`의 `CEREBRAS_API_KEY`가 설정되어 있는지 확인한다. 키 값은 출력하거나 Git에 포함하지 않는다.
2. `venv\\Scripts\\python.exe`는 현재 사용할 수 없으므로, 번들 Python과 `PYTHONPATH=venv\\Lib\\site-packages`를 사용한다.
3. 새 실행은 stdout 버퍼링을 해제(`-u`)해 `tmp\\cerebras_rerun.log`와 `tmp\\cerebras_rerun.error.log`에서 단계 진행을 확인한다. `tmp/`는 Git 추적 대상이 아니다.

## 권장 재개 실행

동일 입력과 Cerebras 모델을 사용하되 문맥 예산을 적용한다. PowerShell에서 공백이 든 보고서 경로를 하나의 인수로 유지해야 한다.

```powershell
$env:PYTHONPATH = 'venv\\Lib\\site-packages'
& 'C:\\Users\\takeu\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' -u main.py `
  --profile test-cerebras `
  --report 'sample_data\\(기획보고서) 기관고유 연구성과 연계형 민관융합 기술개발_인쇄 요청본_20260330.md' `
  --report-project-id institutional-outcomes-civil-convergence-2027 `
  --evidence 'sample_data\\NTIS_유사사업.md' `
  --evidence 'sample_data\\정책근거.md' `
  --evidence 'sample_data\\시장조사.txt' `
  --year 2027
```

## 완료 후 검수 순서

1. 새 `results/institutional-outcomes-civil-convergence-2027/<execution-id>/` 폴더를 확인한다.
2. `04_예산조정안.md`와 `06_최종결정.md`에서 원안·조정안·최종 승인 예산이 기획보고서의 검증값 **226억 원**과 일치하는지 확인한다.
3. `14_검증보고서.md`에서 출처 행 범위 오류, `[확인 필요]`가 붙은 미확인 사실, 예산 불일치 경고를 검토한다. 경고가 있으면 배포하지 않고 원인을 보완한다.
4. `심의종합리포트.html`의 연도, 검증 상태, 목차 및 내용을 열어 확인한다.
5. 검수 통과본만 `tools/protect_report.mjs`로 암호화해 해당 실행 폴더의 `web_public/index.html`과 GitHub 배포용 `results/index.html`을 갱신한다. 비밀번호·원문 보고서·근거자료·일반 결과물은 공개 저장소에 커밋하지 않는다.

## Git 유의사항

- 작업 트리에 `venv/` 관련 대량 변경이 있을 수 있으므로, 이후 커밋 시 프로젝트 코드·문서·명시적으로 허용된 배포용 `results/index.html`만 선택해 스테이징한다.
- 새 실행 결과 중 공개가 필요한 암호화 배포본만 별도 확인 후 커밋한다. 일반 `results/` 하위 결과와 `sample_data/`의 기획·근거 문서는 제외한다.
