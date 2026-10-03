from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, SlakeBatch
from app.services.rules import (
    RuleError,
    assert_can_set_pond_status,
    latest_batch_for_pond,
    parse_peak_temp,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        pond_cards.append({"pond": pond, "batch": batch})

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    if selected_id:
        selected = next((c["pond"] for c in pond_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        status_labels=STATUS_LABELS,
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    pond = Pond.query.get_or_404(pond_id)
    status = request.form.get("status") or pond.status
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()

    def back_to_drawer():
        # 无论成败都回到完整平面图：瓦片网格照常渲染、抽屉保持展开、登录态不受影响
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    try:
        # 非法峰值（非数字 / nan / inf / 0 / 负数）在此被中文挡下，不入库
        peak = parse_peak_temp(peak_raw)
    except RuleError as exc:
        flash(str(exc), "error")
        return back_to_drawer()

    try:
        # 对池位行加锁，串行化同一池位的并发保存：
        # 连点 / 并发提交依次校验、依次落库，最终只留一版合法值
        locked_pond = db.session.get(
            Pond, pond.id, with_for_update=True, populate_existing=True
        )
        batch = latest_batch_for_pond(locked_pond)
        if batch is None:
            raise RuleError("该池尚无熟化批次，无法登记峰值或出灰")
        batch = db.session.get(
            SlakeBatch, batch.id, with_for_update=True, populate_existing=True
        )
        if peak is not None:
            batch.peak_temp_c = peak
        batch.notes = notes
        assert_can_set_pond_status(locked_pond, status)
        locked_pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("作业保存失败，请重试", "error")

    return back_to_drawer()
