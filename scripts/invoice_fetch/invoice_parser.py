"""Invoice parser — extract structured fields from PDF text and email subjects."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from .log_privacy import mask_amount, mask_invoice_number, mask_path, redact_text

_log = logging.getLogger(__name__)


@dataclass
class InvoiceInfo:
    """Parsed invoice fields."""

    invoice_number: str = ""
    invoice_code: str = ""
    invoice_date: str = ""       # YYYY-MM-DD
    amount: str = ""             # pre-tax
    total_amount: str = ""       # tax-inclusive
    seller_name: str = ""
    buyer_name: str = ""
    invoice_type: str = ""
    parse_success: bool = False
    parse_note: str = ""
    raw_text: str = ""


# ── Shared date normalizer ──────────────────────────────────────────

def normalize_date(s: str) -> str:
    """Normalize date strings like ``2026年05月01日`` → ``2026-05-01``."""
    if not s:
        return ""
    # Normalize standard CJK radicals and Kangxi radical variants of Month (\u2f26, \u2f49) and Day (\u2f3c, \u2f47, \u2f52)
    s = s.strip()
    s = s.replace("\u2f26", "月").replace("\u2f49", "月")
    s = s.replace("\u2f3c", "日").replace("\u2f47", "日").replace("\u2f52", "日")
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    return s



# ── PDF parsing ──────────────────────────────────────────────────────

class InvoiceParser:
    """Extract invoice metadata from PDF files."""

    def __init__(self):
        self._pdfplumber = None

    def _plumber(self):
        if self._pdfplumber is None:
            import pdfplumber
            self._pdfplumber = pdfplumber
        return self._pdfplumber

    def parse_pdf(self, path: str) -> InvoiceInfo:
        info = InvoiceInfo()
        if not os.path.exists(path):
            info.parse_note = "文件不存在"
            return info

        try:
            with self._plumber().open(path) as pdf:
                if not pdf.pages:
                    info.parse_note = "PDF无页面"
                    return info
                text = ""
                for p in pdf.pages[:2]:
                    t = p.extract_text()
                    if t:
                        text += t + "\n"

            if not text.strip():
                info.parse_note = "无法提取文本(可能为扫描件)"
                return info

            # Normalize standard CJK radicals and Kangxi radical variants in the entire text first to enable accurate regex matching
            text = text.replace("\u2f26", "月").replace("\u2f49", "月")
            text = text.replace("\u2f3c", "日").replace("\u2f47", "日").replace("\u2f52", "日")

            info.raw_text = text[:2000]

            if self._parse_transport_receipt(text, info):
                return info

            if not self._looks_like_invoice(text):
                info.parse_note = "内容不像发票"
                return info

            # ── Invoice number (8-20 digits) ──
            info.invoice_number = self._field(text, [
                r"发票号码\s*[:：]\s*(\d{8,20})",
                r"发\s*票\s*号\s*码\s*[:：]?\s*(\d{8,20})",
                r"No\s*[:：.]?\s*(\d{8,20})",
            ])
            # Fallback: look for standalone number near "发票" context
            if not info.invoice_number:
                # Exclude candidate numbers appearing on lines containing bank/account keywords to prevent wrong account extraction
                nums_8 = []
                nums_20 = []
                bank_kws = ["账号", "开户行", "银行", "支行", "分行", "建行", "工行", "农行", "招行", "中行", "交行", "邮储", "信用社", "账户"]
                for line in text.splitlines():
                    if any(kw in line for kw in bank_kws):
                        continue
                    # 8-digit numbers NOT followed by letters (to exclude taxpayer IDs)
                    nums_8.extend(re.findall(r"(?<!\d)(\d{8})(?!\d|[A-Za-z])", line))
                    # Also look for longer numbers (20-digit 全电发票 numbers)
                    nums_20.extend(re.findall(r"(?<!\d)(\d{20})(?!\d)", line))

                if nums_20:
                    info.invoice_number = nums_20[0]
                elif nums_8:
                    info.invoice_number = nums_8[0]

            # ── Invoice code (10-12 digits) ──
            info.invoice_code = self._field(text, [
                r"发票代码\s*[:：]\s*(\d{10,12})",
                r"发\s*票\s*代\s*码\s*[:：]?\s*(\d{10,12})",
            ])
            if not info.invoice_code:
                nums_long = re.findall(r"(?<!\d)(\d{10,12})(?!\d)", text)
                for n in nums_long:
                    if n != info.invoice_number:
                        info.invoice_code = n
                        break

            # ── Try extracting from filename (e.g. 031002500111_11803786.pdf) ──
            fname = os.path.basename(path)
            fname_nums = re.findall(r"(\d{8,12})", fname)
            if not info.invoice_number and len(fname_nums) >= 2:
                info.invoice_code = fname_nums[0]
                info.invoice_number = fname_nums[1]
            elif not info.invoice_number and len(fname_nums) == 1:
                info.invoice_number = fname_nums[0]

            # ── Date ──
            raw_date = self._field(text, [
                r"开票日期\s*[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)",
                r"开\s*票\s*日\s*期\s*[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?)",
                r"开票日期\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            ])
            if not raw_date:
                # Disjoint layout: "2026 05 15" near "开票日期"
                m = re.search(r"(\d{4})\s+(\d{2})\s+(\d{2})", text)
                if m:
                    raw_date = f"{m[1]}年{m[2]}月{m[3]}日"
            # Standalone date fallback (e.g. YYYY年MM月DD日 anywhere in text if still not found)
            if not raw_date:
                m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)
                if m:
                    raw_date = f"{m[1]}年{m[2]}月{m[3]}日"
                else:
                    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
                    if m:
                        raw_date = f"{m[1]}-{m[2]}-{m[3]}"
            info.invoice_date = normalize_date(raw_date)

            # ── Amounts ──
            info.amount = self._field(text, [
                r"合\s*计\s*[¥￥]?\s*([\d,]+\.\d{2})",
                r"金\s*额\s*[¥￥]?\s*([\d,]+\.\d{2})",
            ]).replace(",", "")
            info.total_amount = self._field(text, [
                r"价税合计\s*[（(]?大写[）)]?\s*.*?[¥￥]\s*([\d,]+\.\d{2})",
                r"价税合计.*?[¥￥]\s*([\d,]+\.\d{2})",
                r"[（(]小写[）)]\s*[¥￥]?\s*([\d,]+\.\d{2})",
                r"小写\s*[¥￥]?\s*([\d,]+\.\d{2})",
                r"\(小写\)\s*[¥￥]?\s*([\d,]+\.\d{2})",
                r"[圆圓]整\s*[¥￥]\s*([\d,]+\.\d{2})",
                r"[¥￥]\s*([\d,]+\.\d{2})\s*$",
                r"价\s*税\s*合\s*计.*?([\d,]+\.\d{2})",
                r"总计\s*[¥￥]?\s*([\d,]+\.\d{2})",
                r"合计金额\s*[¥￥]?\s*([\d,]+\.\d{2})",
            ]).replace(",", "")

            # ── Names ──
            info.seller_name = self._name(text, [
                r"销\s*名\s*称\s*[:：]\s*(.+?)(?=\s*(?:买|方|信|统一社会|项目名称|规格型号|备注|开票人|$))",
                r"销售方名称\s*[:：]\s*(.+?)(?:\n|购买方|购方|买方|纳税人|地\s*址|统一社会|备注|项目名称|规格型号)",
                r"销售方信息\s*[:：]?\s*(.+?)(?:\n|购买方|购方|买方|纳税人|统一社会|备注|项目名称|规格型号)",
                r"销\s*售\s*方\s*[:：]?\s*(.+?)(?:\n|购买方|购方|买方|纳税人|统一社会)",
                r"收款方\s*[:：]\s*(.+?)(?:\n|购买方|购方|买方|$)",
                # Two-column merged layout: "名称<buyer>名称<seller>" or "名称<buyer>\n名称<seller>"
                r"名称[^\n]{1,30}名称\s*([^\n]{3,80}?)(?=\s*(?:统一社会|纳税人|地址|开户|$))",
            ])
            if not info.seller_name or len(info.seller_name) <= 1:
                info.seller_name = self._company_after_anchor(text, "销")
            # Final fallback: look for a company name anywhere in the text.
            if not info.seller_name or len(info.seller_name) <= 1:
                names = re.findall(
                    r"[\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff（）()·\-A-Za-z0-9]{2,80}"
                    r"(?:有限公司|有限责任公司|股份公司|集团|合伙企业|有限合伙|分公司|门店|店|餐饮|公司|工作室|商行|馆|部|厂)"
                    r"(?:[（(][^）)]+[）)])?",
                    text
                )
                if names:
                    _prefix_noise = re.compile(r"^(?:名称|信息|方名称|方信息|销售方|购买方)+")
                    filtered = [
                        _prefix_noise.sub("", n)
                        for n in names
                        if InvoiceParser._is_company_like(_prefix_noise.sub("", n))
                    ]
                    if filtered:
                        info.seller_name = filtered[-1]
            if not info.seller_name or len(info.seller_name) <= 1:
                if "非税收入" in text:
                    m = re.search(r"([^\n]{2,10}财政[厅局]|[^\n]{2,10}税务[局厅])", text)
                    if m:
                        info.seller_name = m[1].strip()
                    else:
                        info.seller_name = "江苏省财政厅"

            info.buyer_name = self._name(text, [
                r"购\s*名\s*称\s*[:：]\s*(.+?)(?=\s*(?:销|方|信|统一社会|项目名称|规格型号|备注|开票人|$))",
                r"购买方名称\s*[:：]\s*(.+?)(?:\n|销售方|销方|卖方|纳税人|地\s*址|统一社会|备注|项目名称|规格型号)",
                r"购买方信息\s*[:：]?\s*(.+?)(?:\n|销售方|销方|卖方|纳税人|统一社会|备注|项目名称|规格型号)",
                r"购\s*买\s*方\s*[:：]?\s*(.+?)(?:\n|销售方|销方|卖方|纳税人|统一社会)",
                r"交\s*款\s*人\s*[:：]\s*(.+?)(?:\n|统一社会|项目|票据|$)",
            ])
            if not info.buyer_name or len(info.buyer_name) <= 1:
                info.buyer_name = self._company_after_anchor(text, "购")
            if not info.buyer_name or len(info.buyer_name) <= 1:
                names = re.findall(
                    r"[\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff（）()·\-A-Za-z0-9]{2,80}"
                    r"(?:有限公司|有限责任公司|股份公司|集团|合伙企业|有限合伙|分公司|门店|店|餐饮|公司|工作室|商行|馆|部|厂)"
                    r"(?:[（(][^）)]+[）)])?",
                    text
                )
                if names:
                    filtered = [n for n in names if InvoiceParser._is_company_like(n)]
                    if len(filtered) >= 2:
                        info.buyer_name = filtered[0]  # first company is usually buyer
                    elif filtered:
                        info.buyer_name = filtered[0]
            if not info.buyer_name or len(info.buyer_name) <= 1:
                m = re.search(r"交\s*款\s*人\s*[:：]\s*([^\n\s]{2,10})", text)
                if m:
                    info.buyer_name = m[1].strip()

            # Fallback for disjoint layout: "名称：<buyer>\n...\n名称：<seller>"
            if (not info.buyer_name or len(info.buyer_name) <= 1) or (not info.seller_name or len(info.seller_name) <= 1) or (info.buyer_name == info.seller_name):
                name_matches = re.findall(r"名\s*称\s*[:：]\s*([^\n\s]+)", text)
                if len(name_matches) >= 2:
                    cand1 = re.sub(r"\s+", "", name_matches[0]).strip(",:：，,。；; ")
                    cand2 = re.sub(r"\s+", "", name_matches[1]).strip(",:：，,。；; ")
                    if cand1 and not any(tk in cand1 for tk in ["项目", "金额", "地址", "银行", "纳税人"]):
                        if not info.buyer_name or len(info.buyer_name) <= 1 or info.buyer_name == cand2:
                            info.buyer_name = cand1
                    if cand2 and not any(tk in cand2 for tk in ["项目", "金额", "地址", "银行", "纳税人"]):
                        if not info.seller_name or len(info.seller_name) <= 1 or info.seller_name == cand1:
                            info.seller_name = cand2


            # ── Dedicated Railway Ticket Parsing Override ──
            if "铁路" in text or "电子客票" in text or "12306" in text or "铁一发路" in text:
                m_amt = re.search(r"[￥¥]\s*([\d,]+\.\d{2})", text)
                if m_amt:
                    info.total_amount = m_amt[1].replace(",", "")
                    info.amount = info.total_amount
                info.seller_name = "中国国家铁路集团有限公司"
                info.invoice_type = "铁路电子客票"

            # Repair unbalanced parentheses
            info.seller_name = InvoiceParser._repair_company_name(info.seller_name)
            info.buyer_name = InvoiceParser._repair_company_name(info.buyer_name)

            # Cross validation: buyer and seller should not be identical or contain each other
            if info.buyer_name and info.seller_name:
                if info.buyer_name == info.seller_name or info.buyer_name in info.seller_name or info.seller_name in info.buyer_name:
                    # Resolve identity: Usually buyer is correct (first matched/payer)
                    # and seller fell back to buyer. Clean it or fallback seller.
                    names = re.findall(
                        r"[\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff（）()·\-A-Za-z0-9]{2,80}"
                        r"(?:有限公司|有限责任公司|股份公司|集团|合伙企业|有限合伙|分公司|门店|店|餐饮|公司|工作室|商行|馆|部|厂)"
                        r"(?:[（(][^）)]+[）)])?",
                        text
                    )
                    filtered = [n for n in names if InvoiceParser._is_company_like(n) and n != info.buyer_name]
                    if filtered:
                        info.seller_name = filtered[-1]
                    else:
                        info.seller_name = ""

            # Repair again after possible cross-validation update
            info.seller_name = InvoiceParser._repair_company_name(info.seller_name)
            info.buyer_name = InvoiceParser._repair_company_name(info.buyer_name)

            detected_invoice_type = self._invoice_type(text)
            if info.invoice_type != "??????" or detected_invoice_type == "??????":
                if detected_invoice_type:
                    info.invoice_type = detected_invoice_type

            if info.invoice_number:
                info.parse_success = True
                _log.info("解析成功: 号码=%s 日期=%s 金额=%s 销方=%s",
                          mask_invoice_number(info.invoice_number),
                          redact_text(info.invoice_date, "date"),
                          mask_amount(info.total_amount),
                          redact_text(info.seller_name, "seller"))
            else:
                info.parse_note = "未提取到发票号码"

        except Exception as exc:
            info.parse_note = f"解析异常: {exc}"
            _log.error("PDF 解析出错 %s: %s", mask_path(path), exc)

        return info

    @staticmethod
    def _parse_transport_receipt(text: str, info: InvoiceInfo) -> bool:
        """Parse bilingual ride receipts without treating them as tax invoices."""
        low = text.lower()
        markers = (
            "order id",
            "ride city",
            "itinerary info",
            "time of departure",
            "grand total",
            "订单号",
            "用车城市",
            "行程信息",
            "用车时间",
            "总计",
        )
        if sum(1 for marker in markers if marker in low) < 3:
            return False

        order_match = re.search(
            r"(?im)^\s*(?:order\s+id|订单号)\s*[:：]\s*([A-Za-z0-9_-]{8,64})\s*$",
            text,
        )
        date_match = re.search(
            r"(?:time\s+of\s+departure[^\n]*|用车时间[^\n]*)"
            r"[:：]\s*\[?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            text,
            re.IGNORECASE,
        )
        amount_match = re.search(
            r"(?:grand\s+total[^\n]*?|总计[^\n]*?)"
            r"[:：]?\s*(?:CNY|RMB|USD|EUR|SGD|HKD|JPY|GBP|AUD|CAD|S\$|¥|￥|\$)?"
            r"\s*(?<![\d.])([\d,]+\.\d{2})(?!\d)",
            text,
            re.IGNORECASE,
        )

        if not order_match:
            info.parse_note = "网约车电子收据未提取到订单号"
            return False

        info.invoice_number = order_match[1].strip()
        info.invoice_date = normalize_date(date_match[1]) if date_match else ""
        info.total_amount = amount_match[1].replace(",", "") if amount_match else ""
        info.amount = info.total_amount
        info.invoice_type = "网约车电子收据"
        info.parse_success = True
        info.parse_note = "已识别网约车电子收据"
        return True

    @staticmethod
    def _repair_company_name(name: str) -> str:
        name = re.sub(r"\s+", "", str(name or "").strip())
        name = name.strip(",:：，,。；; ")

        # 中文括号：有“（”但没有“）”，且括号内内容像合法组织后缀时，补“）”
        if name.count("（") > name.count("）"):
            tail = name.rsplit("（", 1)[-1]
            if tail and re.search(r"(有限合伙|合伙企业|有限公司|有限责任公司|股份有限公司|分公司|门店|店|公司|工作室|商行|馆|部|厂)$", tail):
                name += "）"

        # 英文括号：有“(”但没有“)”，且括号内内容像合法组织后缀时，补“)”
        if name.count("(") > name.count(")"):
            tail = name.rsplit("(", 1)[-1]
            if tail and re.search(r"(有限合伙|合伙企业|有限公司|有限责任公司|股份有限公司|分公司|门店|店|公司|工作室|商行|馆|部|厂)$", tail):
                name += ")"

        return name

    # ── Internal ─────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_invoice(text: str) -> bool:
        kws = ["发票", "发 票", "invoice", "税额", "价税合计",
               "纳税人识别号", "开票日期", "销售方", "购买方",
               "增值税", "国家税务", "电子发票"]
        low = text.lower()
        return sum(1 for k in kws if k.lower() in low) >= 2

    @staticmethod
    def _field(text: str, patterns: list[str]) -> str:
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m[1]
        return ""

    @staticmethod
    def _is_company_like(name: str) -> bool:
        """Return True if the candidate resembles a real company name."""
        if not name:
            return False

        compact = re.sub(r"\s+", "", name)
        compact = compact.strip("（）()[]{}【】<>《》,，。；;:：·-—|")
        if not compact:
            return False

        noise_tokens = {
            "章", "公章", "财务章", "发票章", "签章", "印", "合同章",
            "（章）", "(章)", "（印）", "(印)",
            "发票代码", "发票号码", "开票日期", "校验码", "机器编号",
            "统一社会", "纳税人识", "纳税识别", "项目名称", "规格型号",
            "价税合计", "合计金额", "地址电话", "开户银行", "银行账号",
            "名称", "信息", "发票", "买方", "卖方", "销售方", "购买方",
        }
        if any(token in compact for token in noise_tokens):
            return False

        suffixes = (
            "有限责任公司", "有限公司", "股份有限公司", "合伙企业", "有限合伙",
            "集团", "分公司", "门店", "店", "餐饮", "公司", "工作室", "商行",
            "馆", "部", "厂",
        )
        if any(s in compact for s in suffixes):
            return True

        # Some OCR outputs drop the suffix. Keep only reasonably long CJK names (including radicals).
        return bool(re.fullmatch(r"[\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff]{4,}", compact))

    @staticmethod
    def _name(text: str, patterns: list[str]) -> str:
        for p in patterns:
            m = re.search(p, text, re.DOTALL)
            if m:
                n = re.sub(r"^(?:方名称|方信息|名\s*称|信息|名称|方)?[:：]?", "", m[1].strip())
                n = re.sub(r"\s+", "", n)
                n = n.strip(",:：，,。；; ")
                n = InvoiceParser._repair_company_name(n)
                if len(n) <= 80 and InvoiceParser._is_company_like(n):
                    return n
        return ""

    @staticmethod
    def _company_after_anchor(text: str, anchor: str) -> str:
        """Find a company name that follows a labeled anchor like 销售方 or 购买方."""
        lines = [re.sub(r"\s+", "", line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        anchor = re.sub(r"\s+", "", anchor)
        company_pat = re.compile(
            r"[\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff（）()·\-A-Za-z0-9]{2,80}?"
            r"(?:有限公司|有限责任公司|股份公司|集团|合伙企业|有限合伙|分公司|门店|店|餐饮|公司|工作室|商行|馆|部|厂)"
            r"(?:（[^）]{1,20}）)?"
        )
        stop_pat = r"(?:统一社会信用代码|纳税人识别号|地址电话|地址|电话|开户行|账号|项目名称|规格型号|金额|税额|购买方|销售方|备注)"

        for idx, line in enumerate(lines):
            if anchor not in line:
                continue

            window = "".join(lines[idx:idx + 4])
            tail = window.split(anchor, 1)[1]
            # Strip non-alphanumeric CJK and radical prefix first
            tail = re.sub(r"^[^a-zA-Z0-9\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff]+", "", tail)
            tail = re.sub(r"^(?:方名称|方信息|名\s*称|信息|名称|方)?[:：]?", "", tail)
            tail = re.split(stop_pat, tail, maxsplit=1)[0]
            tail = tail.strip("：:，,。；; ")
            match = company_pat.search(tail)
            if match:
                return match.group(0)

            if idx + 1 < len(lines):
                next_line = re.split(stop_pat, lines[idx + 1], maxsplit=1)[0]
                # Strip non-alphanumeric CJK and radical prefix first
                next_line = re.sub(r"^[^a-zA-Z0-9\u4e00-\u9fff\u2e80-\u2fd5\uf900-\ufaff]+", "", next_line)
                next_line = re.sub(r"^(?:方名称|方信息|名\s*称|信息|名称|方)?[:：]?", "", next_line)
                next_line = next_line.strip("：:，,。；; ")
                match = company_pat.search(next_line)
                if match:
                    return match.group(0)
                if next_line and InvoiceParser._is_company_like(next_line):
                    return next_line

        return ""

    @staticmethod
    def _invoice_type(text: str) -> str:
        for pat, label in [
            (r"铁路电子客票", "铁路电子客票"),
            (r"增值税电子普通发票", "增值税电子普通发票"),
            (r"增值税电子专用发票", "增值税电子专用发票"),
            (r"增值税普通发票", "增值税普通发票"),
            (r"增值税专用发票", "增值税专用发票"),
            (r"全电发票", "全电发票"),
            (r"电子发票", "电子发票"),
        ]:
            if re.search(pat, text):
                return label
        return ""


# ── Subject-line fallback ────────────────────────────────────────────

def parse_subject(subject: str) -> dict:
    """Extract invoice fields from an email subject line.

    Used when no PDF attachment is available (link-only emails).
    """
    if not subject:
        return {}

    info: dict = {}

    m = re.search(r"发票号码[：:]\s*(\d{8,20})(?:\D|$)", subject)
    if m:
        info["invoice_number"] = m[1]

    m = re.search(r"发票代码[：:]\s*(\d{10,12})", subject)
    if m:
        info["invoice_code"] = m[1]

    m = re.search(r"(?:价税合计)?金额[为：:]\s*([\d,.]+)", subject)
    if m:
        info["total_amount"] = m[1].replace(",", "")

    m = re.search(r"来自【(.+?)】", subject)
    if m:
        info["seller_name"] = m[1]
    else:
        m = re.search(r"【(.+?)】开具", subject)
        if m:
            info["seller_name"] = m[1]
        else:
            m = re.search(r"收到.+?【(.+?)】", subject)
            if m:
                info["seller_name"] = m[1]

    m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", subject)
    if m:
        info["invoice_date"] = normalize_date(f"{m[1]}-{m[2]}-{m[3]}")

    if "电子发票" in subject:
        info["invoice_type"] = "电子发票"
    elif "增值税" in subject:
        info["invoice_type"] = "增值税发票"

    return info


def parse_html_body(html: str) -> dict:
    """Extract invoice fields from email HTML body text.

    Used as a fallback when no PDF is downloadable.
    """
    if not html:
        return {}

    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ").strip()
    except Exception:
        text = html

    info: dict = {}

    # Remove excessive spaces
    text = re.sub(r"\s+", " ", text)

    # 1. Try finding invoice number
    m = re.search(r"(?:发票号码|发票号|单号)\s*[：:]?\s*(\d{8,20})", text)
    if m:
        info["invoice_number"] = m[1]

    # 2. Try finding total amount
    # Matches patterns like: 发票金额：27.90, 合计金额: 100.00, 金额: ￥50.00
    m = re.search(r"(?:发票金额|合计金额|合计|金额|价税合计|小写)\s*[：:]?\s*[¥￥\s]*([\d,]+\.\d{2})", text)
    if m:
        info["total_amount"] = m[1].replace(",", "")

    # 3. Try finding seller name
    m = re.search(r"(?:来自|开商|开具方|销方|销售方)\s*[：:]?\s*([（(]?[\u4e00-\u9fff]{2,}(?:有限公司|股份公司|集团|店|合伙企业|分公司|餐饮))", text)
    if m:
        info["seller_name"] = m[1]

    return info
