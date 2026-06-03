"""slack_sender.py — 일보 텍스트를 Slack 채널에 발송.

인증: Slack Bot Token (xoxb-...). Webhook 아님 (추후 reaction/reply 대비).
채널: .env의 SLACK_CHANNEL (채널 ID 권장. 이름이면 봇이 해당 채널에 초대돼 있어야 함).
DRY_RUN=true 면 발송하지 않고 stdout에만 출력.
발송 실패 시 예외를 던진다 (main에서 잡아 종료 코드 1 처리).

단독 실행:
  echo "메시지" | python -m slack_sender     (stdin 텍스트 발송/미리보기)
  python -m slack_sender                       (기본 테스트 메시지)
"""

import sys

import config

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:  # pragma: no cover
    WebClient = None
    SlackApiError = Exception


def _client():
    """발송 가능 상태 검증 후 WebClient 반환."""
    if WebClient is None:
        raise RuntimeError("slack_sdk 패키지가 설치되지 않았습니다. pip install slack-sdk")
    if not config.SLACK_BOT_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN 이 .env에 없습니다.")
    if not config.SLACK_CHANNEL:
        raise RuntimeError("SLACK_CHANNEL 이 .env에 없습니다.")
    return WebClient(token=config.SLACK_BOT_TOKEN)


def _post(client, text: str, thread_ts: str = None) -> str:
    """한 건 발송. 성공 시 메시지 ts 반환, 실패 시 예외."""
    try:
        resp = client.chat_postMessage(
            channel=config.SLACK_CHANNEL,
            text=text,
            thread_ts=thread_ts,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as e:
        # Slack API 에러 메시지를 명확히 노출 (channel_not_found, not_in_channel 등)
        err = e.response.get("error") if getattr(e, "response", None) else str(e)
        raise RuntimeError(f"Slack 발송 실패: {err}") from e

    if not resp.get("ok", False):
        raise RuntimeError(f"Slack 발송 실패: {resp.get('error', 'unknown')}")
    return resp.get("ts")


def send(text: str) -> bool:
    """단일 텍스트를 Slack에 발송. DRY_RUN이면 stdout 출력만.

    성공 시 True, 실패 시 예외. (fallback / 단독 실행용)
    """
    if config.DRY_RUN:
        print("[DRY_RUN] 다음 내용이 발송될 예정:")
        print(text)
        return True

    _post(_client(), text)
    return True


def send_threaded(parent_text: str, section_texts: list) -> bool:
    """메인 메시지를 채널에 보내고, 각 섹션을 그 스레드에 단다.

    채널에는 parent_text(타이틀+요약)만 뜨고 상세는 스레드로 들어가 모바일 부담을 줄인다.
    DRY_RUN이면 발송 없이 stdout으로 구조를 미리보기. 성공 시 True, 실패 시 예외.
    """
    if config.DRY_RUN:
        print("[DRY_RUN] 채널 메인 메시지:")
        print(parent_text)
        for i, s in enumerate(section_texts, 1):
            print(f"\n[DRY_RUN] 스레드 댓글 {i}:")
            print(s)
        return True

    client = _client()
    parent_ts = _post(client, parent_text)
    for s in section_texts:
        if s and s.strip():
            _post(client, s, thread_ts=parent_ts)
    return True


if __name__ == "__main__":
    stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    msg = stdin_text.strip() or "shopl-daily-bot 테스트 메시지입니다."
    try:
        send(msg)
        if not config.DRY_RUN:
            print(f"[slack_sender] 발송 완료 → {config.SLACK_CHANNEL}", file=sys.stderr)
    except Exception as e:
        print(f"[slack_sender] {e}", file=sys.stderr)
        sys.exit(1)
