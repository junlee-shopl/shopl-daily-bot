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


def send(text: str) -> bool:
    """일보 텍스트를 Slack에 발송. DRY_RUN이면 stdout 출력만.

    성공 시 True, 실패 시 예외.
    """
    if config.DRY_RUN:
        print("[DRY_RUN] 다음 내용이 발송될 예정:")
        print(text)
        return True

    if WebClient is None:
        raise RuntimeError("slack_sdk 패키지가 설치되지 않았습니다. pip install slack-sdk")
    if not config.SLACK_BOT_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN 이 .env에 없습니다.")
    if not config.SLACK_CHANNEL:
        raise RuntimeError("SLACK_CHANNEL 이 .env에 없습니다.")

    client = WebClient(token=config.SLACK_BOT_TOKEN)
    try:
        resp = client.chat_postMessage(
            channel=config.SLACK_CHANNEL,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as e:
        # Slack API 에러 메시지를 명확히 노출 (channel_not_found, not_in_channel 등)
        err = e.response.get("error") if getattr(e, "response", None) else str(e)
        raise RuntimeError(f"Slack 발송 실패: {err}") from e

    if not resp.get("ok", False):
        raise RuntimeError(f"Slack 발송 실패: {resp.get('error', 'unknown')}")
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
