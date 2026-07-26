# 회사 환경 설정 및 작업 재개

이 문서는 공개 저장소만으로 프로젝트를 이어서 실행하기 위한 최소 설정 절차다. 기획보고서·외부 근거자료·일반 심의 결과는 저장소에 포함하지 않는다.

## 1. 코드 받기

```powershell
git clone https://github.com/takeused/20260726-RnD-Deliberation.git
cd 20260726-RnD-Deliberation
git switch codex/secure-rnd-reporting
```

이 브랜치에는 예산 정합성, 출처 검증, 암호화 배포 페이지 개선이 포함되어 있다.

## 2. Python 환경

Python 3.10 이상을 설치한 뒤, 새 가상환경을 만든다. 저장소에 포함된 기존 `venv/`는 사용하거나 커밋하지 않는다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

검증:

```powershell
python -m pytest tests\test_smoke.py -q
python -m compileall -q rdagents
```

## 3. Cerebras API 설정

`.env.example`을 복사해 `.env`를 만들고 회사에서 발급한 Cerebras 키만 넣는다. 키는 채팅·문서·Git·결과물에 기록하지 않는다.

```powershell
Copy-Item .env.example .env
```

필수 값:

```dotenv
CEREBRAS_API_KEY=회사에서_발급한_키
```

권장 선택값:

```dotenv
RDAGENTS_LLM_PROVIDER=cerebras
RDAGENTS_DEEP_THINK_LLM=gpt-oss-120b
RDAGENTS_QUICK_THINK_LLM=gpt-oss-120b
RDAGENTS_LLM_TIMEOUT=120
```

`RDAGENTS_LLM_TIMEOUT`은 외부 모델 호출 한 건이 무한 대기하는 것을 막는 초 단위 제한이다.

## 4. 비공개 입력자료 배치

다음 파일은 회사의 승인된 보안 저장소에서만 받아 `sample_data/`에 둔다. 공개 저장소에 추가하지 않는다.

- 기획보고서 Markdown 원문: `(기획보고서)*.md`
- `NTIS_유사사업.md`
- `정책근거.md`
- `시장조사.txt`

PDF가 원본인 경우 먼저 Markdown으로 변환하고, 페이지/줄 근거를 재확인한다.

## 5. 심의 실행

아래 예시는 Cerebras와 문맥 예산이 적용된 실행이다. 파일명은 회사가 보유한 실제 입력 파일명에 맞춘다.

```powershell
python -u main.py `
  --profile test-cerebras `
  --report 'sample_data\(기획보고서).md' `
  --report-project-id institutional-outcomes-civil-convergence-2027 `
  --evidence 'sample_data\NTIS_유사사업.md' `
  --evidence 'sample_data\정책근거.md' `
  --evidence 'sample_data\시장조사.txt' `
  --year 2027
```

새 결과는 `results/<project-id>/<execution-id>/`에 생성된다.

## 6. 배포 전 필수 검수

1. `04_예산조정안.md`, `06_최종결정.md`의 예산이 기획보고서 검증값과 일치하는지 확인한다.
2. `14_검증보고서.md`가 **통과**인지 확인한다.
3. 확인되지 않은 수치·기관·계약·협약 표현이 있으면 삭제하거나 근거를 첨부한 뒤 검증보고서를 다시 생성한다.
4. `심의종합리포트.html`을 검토한 뒤에만 암호화 배포본을 만든다.

## 7. 암호화 배포

암호는 승인된 별도 전달 경로로만 관리한다. 명령 기록이나 소스코드에 비밀번호를 넣지 않는다.

```powershell
node tools\protect_report.mjs `
  'results\<project-id>\<execution-id>\심의종합리포트.html' `
  'results\<project-id>\<execution-id>\web_public\index.html' `
  '<배포_비밀번호>'
```

GitHub Pages 등에 올릴 수 있는 대상은 암호화된 `results/index.html`뿐이다. 평문 HTML, Markdown 결과, 입력자료는 공개 저장소에 넣지 않는다.

## 8. Git 보안 점검

커밋 전 다음을 확인한다.

```powershell
git status --short
git diff --cached --check
```

다음 항목은 항상 제외한다.

- `.env`, API 키, 비밀번호
- `sample_data/`의 기획보고서·근거자료
- 일반 `results/` 실행 결과 및 평문 보고서
- `venv/`, `.venv/`, `tmp/`, `output/`
