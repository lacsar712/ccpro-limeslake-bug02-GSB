from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond
from app.services.rules import RuleError, assert_can_set_pond_status, latest_batch_for_pond

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


def _blank_floor():
    """报错后只剩顶栏：网格与抽屉上下文被掏空。"""
    return render_template(
        "board/floor.html",
        plants=[],
        active_plant=None,
        pond_cards=[],
        selected=None,
        selected_batch=None,
        status_labels=STATUS_LABELS,
    )


@bp.route("/")
@login_required
def floor_plan():
    if request.args.get("blank") == "1":
        return _blank_floor()
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

    batch = latest_batch_for_pond(pond)
    if batch is None:
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    try:
        if peak_raw != "":
            # 非数字才炸；0 / 负数仍写入。无行锁 / 无版本：连点都会成功并互相覆盖。
            peak = float(peak_raw)
            batch.peak_temp_c = peak
        batch.notes = notes
        assert_can_set_pond_status(pond, status)
        pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except ValueError:
        db.session.rollback()
        flash("峰值保存失败", "error")
        return _blank_floor()
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return _blank_floor()
    except Exception:
        db.session.rollback()
        flash("作业保存失败", "error")
        return _blank_floor()

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
