"""Telegram text message skill for OpenClaw."""

import os
import logging
from typing import Dict, Any

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

ENV_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_DEFAULT_CHAT_ID = "TELEGRAM_DEFAULT_CHAT_ID"


def _get_bot_token() -> str:
    token = os.getenv(ENV_BOT_TOKEN)
    if not token:
        raise ValueError(f"Telegram bot token not set. Set {ENV_BOT_TOKEN}.")
    return token


def _get_default_chat_id() -> str:
    chat_id = os.getenv(ENV_DEFAULT_CHAT_ID)
    if not chat_id:
        raise ValueError(f"Telegram default chat ID not set. Set {ENV_DEFAULT_CHAT_ID}.")
    return chat_id


def send_message(
    text: str,
    chat_id: str = None,
    bot_token: str = None,
    parse_mode: str = "HTML"
) -> Dict[str, Any]:
    """
    Send a plain text message to Telegram.

    Args:
        text: Message text (supports HTML formatting if parse_mode='HTML')
        chat_id: Target chat ID (uses default if None)
        bot_token: Bot token (uses env if None)
        parse_mode: 'HTML' or 'MarkdownV2'

    Returns:
        dict: Telegram API response with 'ok' key
    """
    if requests is None:
        return {"ok": False, "error": "requests not installed"}

    if chat_id is None:
        chat_id = _get_default_chat_id()
        if not chat_id:
            return {"ok": False, "error": "No chat_id and TELEGRAM_DEFAULT_CHAT_ID not set"}

    if bot_token is None:
        try:
            bot_token = _get_bot_token()
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            logger.info(f"Telegram message sent: message_id={result.get('message_id')}")
            return result
        else:
            err = result.get("description", "Unknown error")
            logger.error(f"Telegram message failed: {err}")
            return {"ok": False, "error": err}
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram message network error: {e}")
        return {"ok": False, "error": str(e)}
