"""Optional AI-powered email classifier.

The local-first default is provider='none'. When a cloud provider is enabled,
only masked email subjects and senders are sent to the model. Email bodies,
attachments, PDFs, and downloaded files must not be sent through this module.
"""

from __future__ import annotations

import json
import logging
import re
import time
import requests

from .credentials import get_ai_api_key

_log = logging.getLogger(__name__)

# API endpoints
_ENDPOINTS = {
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}

_DEFAULT_MODELS = {
    "none": "",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
}

_SYSTEM_PROMPT = """\
你是一个邮件分类助手。判断以下邮件是否与"发票"相关。

发票相关包括：电子发票通知、发票下载链接、报销凭证、行程单、水单、开票通知等。
不相关包括：广告、验证码、账单提醒、快递通知、促销、系统通知等。

请对每封邮件返回 JSON 数组，严格按以下格式，不要输出其他内容：
[{"uid": 123, "is_invoice": true, "reason": "包含发票下载链接"}]
"""


class AIClassifier:
    """Batch email classifier using an optional cloud AI provider."""

    def __init__(self, provider: str = "none",
                 model: str = "", batch_size: int = 20):
        self.provider = (provider or "none").lower()
        self.model = model or _DEFAULT_MODELS.get(self.provider, "")
        self.batch_size = batch_size
        self.api_key = ""
        if self.provider != "none":
            self.api_key = get_ai_api_key(self.provider)
        _log.info("AI 分类器: provider=%s, model=%s, batch=%d",
                  self.provider, self.model, batch_size)

    def classify_batch(self, emails: list[dict]) -> list[dict]:
        """Classify emails in batches.

        Args:
            emails: [{"uid": int, "subject": str, "sender": str}, ...]
        Returns:
            [{"uid": int, "is_invoice": bool | None, "reason": str}, ...]
        """
        if self.provider == "none":
            _log.info("AI 分类未启用，%d 封邮件保持待分类", len(emails))
            return self._mark_batch_unclassified(emails, "AI 分类未启用，仅使用本地规则/白名单")

        results = []
        total = len(emails)
        for i in range(0, total, self.batch_size):
            chunk = emails[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            _log.info("  AI 分类: 批次 %d/%d (%d 封)",
                      batch_num, total_batches, len(chunk))
            batch_result = self._call_api(chunk)
            results.extend(batch_result)
        return results

    def _call_api(self, chunk: list[dict]) -> list[dict]:
        """Single API call for a chunk of emails."""
        if self.provider == "deepseek":
            return self._call_deepseek(chunk)
        elif self.provider == "gemini":
            return self._call_gemini(chunk)
        else:
            _log.error("未知 provider: %s", self.provider)
            return self._mark_batch_unclassified(chunk, "未知 AI provider，保持待分类")

    @staticmethod
    def _mask_sensitive_info(text: str) -> str:
        """Mask sensitive info before any cloud AI request.

        Keeps domains and common system email prefixes so the model can still
        classify likely invoice senders. This function is intentionally limited
        to subjects and senders; do not pass email bodies or document text here.
        """
        if not text:
            return ""

        # 1. Mask 11-digit phone numbers: 13812345678 -> 138****5678
        text = re.sub(r'\b(1[3-9]\d)\d{4}(\d{4})\b', r'\1****\2', text)

        # 2. Mask long numeric codes (10+ digits, e.g., order IDs, bank cards, ID numbers)
        # Keep first 2 and last 2 digits, replace middle with ****
        def mask_code(m):
            code = m.group(0)
            return code[:2] + "****" + code[-2:]
        text = re.sub(r'\b\d{10,24}\b', mask_code, text)

        # 3. Mask email prefix if it's not a common system email
        def mask_email(m):
            prefix, domain = m.group(1), m.group(2)
            if len(prefix) <= 2:
                return f"**@{domain}"
            if prefix.lower() in ("no-reply", "noreply", "service", "invoice", "fapiao", "notification", "info", "support"):
                return f"{prefix}@{domain}"
            return f"{prefix[:1]}***{prefix[-1:]}@{domain}"
        text = re.sub(r'([\w\.-]+)@([\w\.-]+\.\w+)', mask_email, text)

        # 4. Mask personal names in Chinese inside display name.
        def mask_chinese_name(m):
            name = m.group(1)
            if 2 <= len(name) <= 4:
                return f'"{name[0]}*"'
            return m.group(0)
        text = re.sub(r'"([\u4e00-\u9fa5]{2,4})"\s*<', r'"\1" <', text)
        text = re.sub(r'"([\u4e00-\u9fa5]{2,4})"', mask_chinese_name, text)

        return text

    def _build_user_message(self, chunk: list[dict]) -> str:
        """Build the user prompt from masked email headers."""
        lines = []
        for e in chunk:
            clean_subject = self._mask_sensitive_info(e['subject'])
            clean_sender = self._mask_sensitive_info(e['sender'])
            lines.append(
                f"UID={e['uid']} | 主题: {clean_subject} | 发件人: {clean_sender}"
            )
        return "\n".join(lines)

    def _call_deepseek(self, chunk: list[dict]) -> list[dict]:
        """Call DeepSeek chat completions API."""
        user_msg = self._build_user_message(chunk)
        try:
            resp = self._post_with_retry(
                _ENDPOINTS["deepseek"],
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.1,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            _log.error("DeepSeek API 调用失败: %s", exc)
            return self._mark_batch_unclassified(chunk, "AI 分类 API 失败，将在下次运行时重试")

        content = resp.json()["choices"][0]["message"]["content"]
        return self._parse_response(content, chunk)

    def _call_gemini(self, chunk: list[dict]) -> list[dict]:
        """Call Gemini generateContent API."""
        user_msg = self._build_user_message(chunk)
        url = _ENDPOINTS["gemini"].format(model=self.model)
        try:
            resp = self._post_with_retry(
                f"{url}?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_msg}]}],
                    "generationConfig": {"temperature": 0.1},
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            _log.error("Gemini API 调用失败: %s", exc)
            return self._mark_batch_unclassified(chunk, "AI 分类 API 失败，将在下次运行时重试")

        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_response(content, chunk)

    def _post_with_retry(self, url: str, **kwargs) -> requests.Response:
        """POST once, then retry once with exponential backoff."""
        last_exc = None
        for attempt in range(2):
            try:
                resp = requests.post(url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    _log.warning("AI 分类 API 失败，1 秒后重试: %s", exc)
                    time.sleep(1)
        raise last_exc

    @staticmethod
    def _mark_batch_unclassified(chunk: list[dict], reason: str) -> list[dict]:
        _log.warning("⚠️ %s，%d 封邮件保持待分类", reason, len(chunk))
        return [
            {"uid": item["uid"], "is_invoice": None, "reason": reason}
            for item in chunk
        ]

    def _parse_response(self, content: str, chunk: list[dict]) -> list[dict]:
        """Parse AI response JSON. On failure, mark batch as unclassified for retry."""
        try:
            text = content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            if not isinstance(data, list):
                data = [data]
            parsed = [
                {
                    "uid": item["uid"],
                    "is_invoice": bool(item["is_invoice"]),
                    "reason": item.get("reason", ""),
                }
                for item in data
                if "uid" in item and "is_invoice" in item
            ]
            # If AI returned fewer results than the batch, mark the missing ones
            parsed_uids = {r["uid"] for r in parsed}
            missing = [e for e in chunk if e["uid"] not in parsed_uids]
            if missing:
                _log.warning("AI 响应缺少 %d 封邮件的结果，保持待分类", len(missing))
                parsed.extend(self._mark_batch_unclassified(missing, "AI 响应缺少该邮件的分类结果"))
            return parsed
        except Exception as exc:
            _log.warning("AI 响应解析失败: %s", exc)
            _log.debug("原始响应: %s", content[:500])
            return self._mark_batch_unclassified(chunk, "AI 响应解析失败，将在下次运行时重试")
