"""Rule-based email classifier — fast, offline, no API cost."""

from __future__ import annotations

# Strong positive signals: definitely invoice-related
INVOICE_KEYWORDS = [
    "发票", "invoice", "fapiao", "电子发票", "增值税",
    "行程单", "水单", "报销", "价税合计",
    "开票", "票据", "发票下载", "发票查看",
    "高铁", "火车票", "铁路", "12306", "电子客票",
    "乘车", "车票", "train", "rail", "railway",
    "报销凭证",
]

# Strong negative signals: definitely NOT invoice-related
EXCLUDE_KEYWORDS = [
    "验证码", "密码", "修改密码", "重置密码",
    "信用卡账单", "还款", "额度", "积分", "信用卡",
    "招聘", "面试", "offer", "简历",
    "系统通知", "退订", "取消订阅",
    "快递", "物流", "签收", "派送",
    "签到", "打卡",
    "相册", "记忆", "回忆",
    "通讯录", "好友",
    "促销", "优惠券", "红包", "会员", "折扣", "秒杀", "限时",
    "课程", "直播", "讲座", "培训",
    "安全提醒", "登录提醒", "异地登录",
    "账号", "绑定", "解绑",
    "问卷", "调查", "评价", "满意度",
    "登机记录", "登机凭证", "乘机凭证", "登机",
]

TECHNICAL_EXCLUDE_KEYWORDS = [
    "github", "gitlab", "gitee", "bitbucket",
    "pull request", "merge request", "workflow run", "github actions",
    "repository", "commit", "issue", "dependabot", "security alert",
    "continuous integration", "ci failed", "actions run",
    "代码审查", "工作流运行", "安全警报",
]

TECHNICAL_EXCLUDE_SENDERS = [
    "notifications@github.com",
    "noreply@github.com",
    "github.com",
    "gitlab.com",
    "gitee.com",
    "bitbucket.org",
]


def classify(subject: str, sender: str) -> tuple[int, str]:
    """Classify an email by keyword rules.

    Returns:
        (is_invoice, reason):
            1, "关键词: xxx"     — confirmed invoice
            0, "排除词: xxx"     — confirmed not invoice
           -1, ""               — uncertain, needs AI
    """
    text = (subject + " " + sender).lower()
    sender_lower = (sender or "").lower()

    technical_signal = next(
        (
            kw for kw in TECHNICAL_EXCLUDE_KEYWORDS
            if kw.lower() in text
        ),
        "",
    )
    technical_sender = next(
        (
            marker for marker in TECHNICAL_EXCLUDE_SENDERS
            if marker.lower() in sender_lower
        ),
        "",
    )
    if technical_signal or technical_sender:
        reason = technical_signal or technical_sender
        return 0, f"技术通知: {reason}"

    positive = [kw for kw in INVOICE_KEYWORDS if kw.lower() in text]
    negative = [kw for kw in EXCLUDE_KEYWORDS if kw.lower() in text]

    if positive and negative:
        return -1, f"规则冲突: 包含词 {positive[0]} / 排除词 {negative[0]}"

    if negative:
        return 0, f"排除词: {negative[0]}"

    if positive:
        return 1, f"关键词: {positive[0]}"

    # Uncertain
    return -1, ""
