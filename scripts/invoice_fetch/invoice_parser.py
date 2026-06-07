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
    item_name: str = ""


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
            info.item_name = self._extract_item_names(text)

            if self._parse_transport_receipt(text, info):
                return info

            is_fiscal = self._is_fiscal_toll_invoice(text)
            if not is_fiscal and not self._looks_like_invoice(text):
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
            # ── Seller-block fallback: extract from "销售方信息" region ──
            if not info.seller_name or len(info.seller_name) <= 1:
                fallback = InvoiceParser._extract_seller_name_fallback(text)
                if fallback:
                    info.seller_name = fallback
            if not info.seller_name or len(info.seller_name) <= 1:
                if "非税收入" in text:
                    m = re.search(r"([^\n]{2,10}财政[厅局]|[^\n]{2,10}税务[局厅])", text)
                    if m:
                        info.seller_name = m[1].strip()

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

            # ── seller_name回填策略 ──
            if (not info.seller_name or len(info.seller_name) <= 1) and is_fiscal:
                issuer, reason = self._extract_fiscal_issuer_fallback(text)
                if reason == "explicit_field" and issuer:
                    info.seller_name = issuer
                    note = "销售方由财政票据开票/收款/执收单位识别"
                    if info.parse_note:
                        info.parse_note += "; " + note
                    else:
                        info.parse_note = note
                elif reason == "stamp_text_near" and issuer:
                    info.seller_name = issuer
                    note = "销售方由财政票据章附近文本推断，建议核对"
                    if info.parse_note:
                        info.parse_note += "; " + note
                    else:
                        info.parse_note = note
                elif reason == "platform_only":
                    note = "检测到财政电子票据平台，但未识别到具体开票单位，建议人工核对红章"
                    if info.parse_note:
                        info.parse_note += "; " + note
                    else:
                        info.parse_note = note

            # Repair again after possible cross-validation update
            info.seller_name = InvoiceParser._repair_company_name(info.seller_name)
            info.buyer_name = InvoiceParser._repair_company_name(info.buyer_name)

            detected_invoice_type = self._invoice_type(text)
            if detected_invoice_type and (
                info.invoice_type != "铁路电子客票"
                or detected_invoice_type == "铁路电子客票"
            ):
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
    def _extract_seller_name_fallback(raw_text: str) -> str:
        """Extract seller name from a seller-info block, avoiding buyer confusion.

        Handles OCR artifacts like "销 售 方 信 息  名称：xxx".
        Returns "" if no seller name could be reliably extracted.
        """
        if not raw_text:
            return ""

        text = raw_text
        # Normalize common OCR spacing for CJK characters around seller keywords
        for pat, repl in [
            (r"销\s*售\s*方\s*信\s*息", "销售方信息"),
            (r"销\s*售\s*方", "销售方"),
            (r"购\s*买\s*方\s*信\s*息", "购买方信息"),
            (r"购\s*买\s*方", "购买方"),
            (r"纳\s*税\s*人\s*识\s*别\s*号", "纳税人识别号"),
            (r"统\s*一\s*社\s*会\s*信\s*用\s*代\s*码", "统一社会信用代码"),
        ]:
            text = re.sub(pat, repl, text)

        # ── 1.  Locate seller-info region ──
        # Try to find "销售方信息" anchor; if missing, use "销售方"
        region_start = -1
        for anchor in ("销售方信息", "销售方"):
            idx = text.find(anchor)
            if idx != -1:
                region_start = idx
                break

        if region_start == -1:
            return ""

        # Cut from region_start until a stop marker (备注, 合计, 价税合计, etc.)
        stop_markers = ["备注", "合计", "价税合计", "项目名称", "规格型号", "开票人", "收款人"]
        region_end = len(text)
        for mk in stop_markers:
            si = text.find(mk, region_start + 1)
            if si != -1 and si < region_end:
                region_end = si

        # Also stop at the buyer-info region if it appears after seller
        buyer_idx = text.find("购买方", region_start + 1)
        if buyer_idx != -1 and buyer_idx < region_end:
            region_end = buyer_idx

        region = text[region_start:region_end]

        # ── 2. Extract "名称:" value within the seller region ──
        # Pattern: 名称: xxx   or  名称： xxx
        name_match = re.search(r"名称\s*[:：]\s*(.+?)(?=\s*(?:纳税人识别号|统一社会信用代码|地址|电话|开户行|账号|$))", region)
        if not name_match:
            name_match = re.search(r"名称\s*[:：]\s*(.+?)$", region)

        if not name_match:
            return ""

        candidate = name_match[1].strip()
        candidate = re.sub(r"\s+", "", candidate)
        candidate = candidate.strip(",:：，,。；; ()（）")

        # ── 3. Clean and validate ──
        # Reject noise tokens
        noise_tokens = {
            "章", "公章", "财务章", "发票章", "签章", "印", "合同章",
            "纳税人识别号", "统一社会信用代码", "名称", "信息",
            "发票代码", "发票号码", "购买方", "销售方",
        }
        for tok in noise_tokens:
            if tok in candidate:
                return ""

        if len(candidate) < 2 or len(candidate) > 80:
            return ""

        if not InvoiceParser._is_company_like(candidate):
            return ""

        _log.debug("seller_name fallback matched by seller block")
        return candidate

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

    def _extract_item_names(self, text: str) -> str:
        """Extract item names (at least first 3) from the PDF text."""
        if not text:
            return ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Find header index
        header_idx = -1
        for idx, line in enumerate(lines):
            # Check for header indicators
            if "项目名称" in line and ("规格型号" in line or "金额" in line or "税额" in line or "数量" in line or "单价" in line):
                header_idx = idx
                break

        # Stop words that indicate the end of the item table or should be skipped
        stop_words = ["合计", "购买方", "销售方", "备注", "注", "密码区", "收款人", "复核", "开票人", "名称"]

        item_candidates = []

        if header_idx != -1:
            # Look at lines below header
            for idx in range(header_idx + 1, len(lines)):
                line = lines[idx]
                if any(line.startswith(sw) or sw in line[:5] for sw in stop_words):
                    break

                parts = line.split()
                if not parts:
                    continue

                name = parts[0]
                # If name is a stop word or starts with a stop word, break or skip
                if any(name.startswith(sw) for sw in stop_words) or any(sw in name for sw in ["税额", "金额", "税率"]):
                    break

                # Check if it looks like a valid item name
                # Should contain CJK characters or starts with *
                if re.search(r"[\u4e00-\u9fff\*]", name):
                    if len(name) > 1:
                        item_candidates.append(name)

        # If no candidates found from header logic, scan the whole text for asterisk patterns
        if not item_candidates:
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                name = parts[0]
                if any(sw in name for sw in stop_words):
                    continue
                m_asterisk = re.search(r"(\*[^*]+\*[^*]*?)(?:\s|$)", name)
                if m_asterisk:
                    item_candidates.append(m_asterisk.group(1).strip())

        # Filter and clean
        valid_items = []
        for item in item_candidates:
            # Clean up
            item = re.sub(r"\s+", "", item)
            # Remove any prefix like "名称:" if it got parsed
            item = re.sub(r"^(?:项目名称|名称)[:：]?", "", item)
            if item and len(item) > 1 and not any(sw in item for sw in stop_words):
                valid_items.append(item)

        # Return first 3 items joined by comma
        return ", ".join(valid_items[:3])

    def _detect_fiscal_platform(self, raw_text: str) -> dict:
        if not raw_text:
            return {"matched": False, "region": "", "platform_name": ""}
        pat = re.compile(
            r"(?P<region>[\u4e00-\u9fff]{2,12}?(?:省|市|自治区|特别行政区))?"
            r"(?:财政电子票据公共服务平台|财政电子票据服务平台|财政票据公共服务平台)"
        )
        m = pat.search(raw_text)
        if m:
            region = m.group("region") or ""
            platform_name = m.group(0)
            return {"matched": True, "region": region, "platform_name": platform_name}
        return {"matched": False, "region": "", "platform_name": ""}

    def _is_fiscal_toll_invoice(self, raw_text: str) -> bool:
        if not raw_text:
            return False
        has = lambda kw: kw in raw_text

        # 1. fiscal platform + toll clue
        platform_info = self._detect_fiscal_platform(raw_text)
        toll_clues = ["通行费", "车牌号", "入站", "出口站", "出口时间", "高速公路", "收费站"]
        cond1 = platform_info["matched"] and any(has(clue) for clue in toll_clues)

        # 2. stamp + toll clue
        stamps = ["财务专用章", "财政电子票据专用章"]
        has_stamp = any(has(s) for s in stamps)
        stamp_toll_clues = ["车牌号", "入站", "出口站", "通行费"]
        cond2 = has_stamp and any(has(clue) for clue in stamp_toll_clues)

        # 3. toll structure
        cond3 = (
            (has("车牌号") and has("入站") and has("出口站"))
            or (has("通行费") and has("高速公路"))
            or (has("通行费") and has("收费站"))
        )

        return bool(cond1 or cond2 or cond3)

    def _is_valid_fiscal_candidate(self, name: str) -> bool:
        if not name:
            return False
        name = re.sub(r"\s+", "", name)
        if not (3 <= len(name) <= 80):
            return False
        noise_words = ["车牌", "入口", "出口", "复核人", "收款人", "开票人", "收费人", "复核", "金额", "合计", "购买方", "购方", "买方", "交款人", "入站", "出口站", "站点", "单价", "数量"]
        if any(w in name for w in noise_words):
            return False
        return True

    def _extract_fiscal_issuer_fallback(self, raw_text: str) -> tuple[str, str]:
        # 1. Explicit fields
        explicit_kws = ["开票单位", "收款单位", "执收单位", "票据单位", "单位名称", "收费单位", "运营单位", "管理单位"]
        for kw in explicit_kws:
            pat = r"" + re.escape(kw) + r"\s*[:：]\s*([^\n\s]{3,80})"
            m = re.search(pat, raw_text)
            if m:
                cand = self._repair_company_name(m.group(1).strip())
                if self._is_valid_fiscal_candidate(cand):
                    return cand, "explicit_field"

        # 2. Stamp proximity
        stamp_kws = ["财务专用章", "财政电子票据专用章"]
        best_candidate = None
        min_dist = 999999
        suffix_pat = r"(?:服务有限公司|运营管理有限公司|高速公路有限公司|有限公司|有限责任公司|股份公司|公司|管理中心|中心|管理处|收费站|服务区|交通运输厅|财政厅|财政局|税务局|分局|支局|管理局|局|厅|院|所)"
        cand_pat = re.compile(r"([\u4e00-\u9fff（）()·\-A-Za-z0-9]{3,80}?" + suffix_pat + r")")

        for stamp in stamp_kws:
            for m_stamp in re.finditer(re.escape(stamp), raw_text):
                idx = m_stamp.start()
                start = max(0, idx - 120)
                end = min(len(raw_text), idx + 120)
                window_text = raw_text[start:end]

                for m_cand in cand_pat.finditer(window_text):
                    cand = self._repair_company_name(m_cand.group(1).strip())
                    if self._is_valid_fiscal_candidate(cand):
                        cand_abs_pos = start + m_cand.start()
                        dist = abs(cand_abs_pos - idx)
                        if dist < min_dist:
                            min_dist = dist
                            best_candidate = cand

        if best_candidate:
            return best_candidate, "stamp_text_near"

        # 3. Platform fallback
        platform_info = self._detect_fiscal_platform(raw_text)
        if platform_info["matched"]:
            return "", "platform_only"

        return "", ""


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
