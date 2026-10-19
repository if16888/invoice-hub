"""Decimal-only tax balance checks; missing values never imply zero tax."""
from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
import re


@dataclass(frozen=True)
class TaxBalance:
    status: str
    message: str = ''

    @property
    def blocking(self) -> bool:
        return self.status in {'invalid', 'mismatch'}


def check_tax_balance(invoice: dict) -> TaxBalance:
    try:
        rate = normalize_tax_rate(invoice.get('tax_rate'))
    except ValueError:
        return TaxBalance('invalid', '税率格式无效')
    values = [invoice.get(key) for key in ('amount', 'tax_amount', 'total_amount')]
    missing = any(value is None or str(value).strip() == '' for value in values)
    try:
        amounts = [Decimal(str(value).strip().replace(',', ''))
                   for value in values if value is not None and str(value).strip()]
        if any(not value.is_finite() or abs(value.adjusted()) > 128
               or len(value.as_tuple().digits) > 128 for value in amounts):
            raise ValueError('invalid amount')
        if missing:
            return TaxBalance('unknown', '价税数据未完整采集，待核对')
        with localcontext() as context:
            context.prec = 256
            mismatch = abs(amounts[0] + amounts[1] - amounts[2]) > Decimal('0.01')
    except (DecimalException, ValueError):
        return TaxBalance('invalid', '价税金额格式无效')
    if rate in {'免税', '不征税'} and amounts[1] != 0:
        return TaxBalance('mismatch', '免税或不征税票据的税额应为 0')
    if mismatch:
        return TaxBalance('mismatch', '税前金额 + 税额与价税合计不一致（容差 0.01 元）')
    return TaxBalance('valid')


def normalize_tax_rate(value: str | None) -> str | None:
    """Use explicit percent units; support exemption and multi-rate invoices."""
    if value is None:
        return None
    value = value.strip().replace('％', '%')
    if value in {'', '免税', '不征税', '多税率'}:
        return value
    rates = re.split(r'[,，、;；]', value)
    normalized = []
    for rate in rates:
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*%\s*', rate)
        if not match or not Decimal('0') <= Decimal(match[1]) <= Decimal('100'):
            raise ValueError('税率请填写百分数（如 13%），或免税、不征税、多税率。')
        normalized.append(format(Decimal(match[1]).normalize(), 'f') + '%')
    return ', '.join(normalized)
