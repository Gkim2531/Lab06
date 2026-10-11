"""通用工具。"""

from decimal import ROUND_HALF_UP, Decimal

_MONEY_CENT = Decimal("0.01")


def money(value) -> str:
    """金额统一为两位小数字符串（ROUND_HALF_UP），保证精确小数计算与输出。"""
    return str(Decimal(value).quantize(_MONEY_CENT, rounding=ROUND_HALF_UP))
