"""石灰熟化池业务规则。"""

from __future__ import annotations

import math

from app.models import Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def parse_peak_temp(raw: str) -> float | None:
    """
    抽屉「登记 / 修正峰值温度」提交值的统一校验。

    空串表示本次不修改峰值，返回 None；
    非数字、非有限值（nan / inf）、不大于 0℃ 的值一律以中文 RuleError 挡下，
    调用方不得将其写入数据库。
    """
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise RuleError("峰值温度必须是数字，请重新填写") from None
    if not math.isfinite(value):
        raise RuleError("峰值温度必须是有效数字，请重新填写")
    if value <= 0:
        raise RuleError("峰值温度必须大于 0℃")
    return value


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


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
