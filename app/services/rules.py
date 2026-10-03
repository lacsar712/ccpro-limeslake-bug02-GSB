"""石灰熟化池业务规则。"""

from __future__ import annotations

import math

from app.models import Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def parse_peak_temp_c(raw: str) -> float:
    """
    解析抽屉登记的峰值温度（℃）。
    非数字、NaN/无穷、0 或负数一律抛 RuleError（中文），调用方不得入库。
    """
    text = (raw or "").strip()
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise RuleError("峰值温度必须是数字，请重新填写") from None
    if not math.isfinite(value):
        raise RuleError("峰值温度必须是有限的数字，请重新填写")
    if value <= 0:
        raise RuleError("峰值温度必须大于 0℃，0 或负数不能入库")
    return value


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: (b.started_at, b.id))


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)
