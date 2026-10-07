"""Validate declared taxpayer-ID schemes without guessing from string length."""
from __future__ import annotations

from dataclasses import dataclass
import re

TAX_ID_TYPES = {
    'unknown': '类型未确定',
    'uscc': '统一社会信用代码',
    'legacy15': '传统 15 位纳税人识别号',
    'other': '其他税号或证件',
}
_USCC_ALPHABET = '0123456789ABCDEFGHJKLMNPQRTUWXY'
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


@dataclass(frozen=True)
class TaxIdCheck:
    status: str
    message: str = ''

    @property
    def blocking(self) -> bool:
        return self.status == 'invalid'


def check_tax_id(value: str | None, id_type: str = 'unknown') -> TaxIdCheck:
    """Validate only a declared supported scheme; validity is not registration proof."""
    if id_type not in TAX_ID_TYPES:
        return TaxIdCheck('invalid', '购方税号类型无效，请重新选择')
    if value is None:
        return TaxIdCheck('unknown')
    text = ''.join(str(value).split()).upper()
    if not text:
        return TaxIdCheck('missing')
    if id_type in {'unknown', 'other'}:
        return TaxIdCheck('unverified')
    if id_type == 'legacy15':
        # Legacy IDs use several allocation rules; this checks only the
        # declared 15-character format, not the issuing body's registration.
        if not re.fullmatch(r'[0-9]{6}[0-9A-Z]{9}', text):
            return TaxIdCheck('invalid', '购方传统税号应为 15 位，前 6 位为数字，后 9 位为数字或字母')
        return TaxIdCheck('format_valid')
    if len(text) != 18 or any(char not in _USCC_ALPHABET for char in text):
        return TaxIdCheck('invalid', '购方统一社会信用代码应为 18 位允许的数字或大写字母')
    check_index = (31 - sum(_USCC_ALPHABET.index(char) * weight
                           for char, weight in zip(text[:17], _USCC_WEIGHTS)) % 31) % 31
    if text[-1] != _USCC_ALPHABET[check_index]:
        return TaxIdCheck('invalid', '购方统一社会信用代码校验位不正确')
    return TaxIdCheck('checksum_valid')
