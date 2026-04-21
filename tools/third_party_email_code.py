import re
import time
from typing import Optional

import requests


def _build_tempmail_headers(email_prefix: str) -> dict:
    email_cookie = f"{email_prefix}%40mailto.plus"
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Sec-Fetch-Site": "same-origin",
        "Cookie": f"email={email_cookie}",
        "Referer": "https://tempmail.plus/zh/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Priority": "u=3, i",
    }


def _listen_latest_mail_id(
    email_prefix: str,
    from_mail: str = "contact@vv.com.sg",
    timeout: int = 60,
    poll_interval: int = 3,
) -> Optional[int]:
    url = f"https://tempmail.plus/api/mails?email={email_prefix}%40mailto.plus&limit=20&epin="
    headers = _build_tempmail_headers(email_prefix)
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("result") and data.get("count", 0) > 0:
                    target_mails = [
                        m
                        for m in data.get("mail_list", [])
                        if m.get("from_mail") == from_mail
                    ]
                    if target_mails:
                        latest_mail = sorted(
                            target_mails,
                            key=lambda x: x["mail_id"],
                            reverse=True,
                        )[0]
                        return latest_mail["mail_id"]
        except Exception:
            pass

        time.sleep(poll_interval)

    return None


def _get_mail_detail(mail_id: int, email_prefix: str) -> Optional[dict]:
    url = f"https://tempmail.plus/api/mails/{mail_id}?email={email_prefix}%40mailto.plus&epin="
    headers = _build_tempmail_headers(email_prefix)
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def _extract_6digit_code(mail_detail: Optional[dict]) -> Optional[str]:
    if not mail_detail or not mail_detail.get("result"):
        return None

    mail_content = mail_detail.get("text", "") or mail_detail.get("html", "")
    if not mail_content:
        return None

    code_match = re.search(r"(\d{6})", mail_content)
    if code_match:
        return code_match.group(1)
    return None


def get_verification_code_from_temp_mailbox(
    email_prefix: str,
    from_mail: str = "contact@vv.com.sg",
    timeout: int = 60,
    poll_interval: int = 3,
) -> Optional[str]:
    """
    从三方邮箱(tempmail.plus)获取6位验证码。

    参数:
    - email_prefix: 邮箱前缀（例如 Llse123456，对应 Llse123456@mailto.plus）
    - from_mail: 发件人过滤，默认 contact@vv.com.sg
    - timeout: 监听超时时间（秒）
    - poll_interval: 轮询间隔（秒）

    返回:
    - 成功: 6位验证码字符串
    - 失败: None
    """
    mail_id = _listen_latest_mail_id(
        email_prefix=email_prefix,
        from_mail=from_mail,
        timeout=timeout,
        poll_interval=poll_interval,
    )
    if not mail_id:
        return None

    mail_detail = _get_mail_detail(mail_id=mail_id, email_prefix=email_prefix)
    return _extract_6digit_code(mail_detail)
