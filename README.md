# shopl-daily-bot

매일 아침 어제 데이터 기준으로 경영지원 일일 보고를 생성하는 봇. (Phase 1: 데이터 수집 레이어)

## 필요 환경

- Python 3.11+

## 설치

```bash
pip install -r requirements.txt
```

## 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고 값을 채운다.

```bash
cp .env.example .env
```

## 실행

```bash
# 전체 수집 (어제 데이터 → 통합 JSON stdout 출력)
python main.py

# 개별 collector 단독 실행
python -m collectors.shopl
python -m collectors.gowid
python -m collectors.popbill
```

수집된 원본 응답은 `tests/fixtures/YYYY-MM-DD/` 아래에 소스별로 저장된다 (gitignore 처리됨).