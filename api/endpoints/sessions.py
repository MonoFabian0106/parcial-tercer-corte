"""GET /sessions/summary — aggregate session metrics filtered by country/device/date."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from api.db import get_session
from api.validators import ValidationError, parse_country, parse_date, parse_enum

bp = Blueprint("sessions", __name__, url_prefix="/sessions")

_ALLOWED_DEVICES = {"mobile", "desktop", "tablet"}


@bp.get("/summary")
def sessions_summary():
    try:
        dt = parse_date(request.args.get("date"))
        country = parse_country(request.args.get("country"), required=False)
        device = parse_enum(
            request.args.get("device"), _ALLOWED_DEVICES, field="device", required=False
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    dt_str = dt.isoformat()
    filters = ["dt = :dt"]
    params: dict[str, object] = {"dt": dt_str}
    if country:
        filters.append("country = :country")
        params["country"] = country
    if device:
        filters.append("device_type = :device")
        params["device"] = device

    where = " AND ".join(filters)
    query = text(f"""
        SELECT
            COALESCE(SUM(unique_sessions), 0)                                AS total_sessions,
            COALESCE(SUM(page_views), 0)                                     AS total_page_views,
            CASE
                WHEN SUM(page_views) > 0
                THEN SUM(avg_time_on_page * page_views) / SUM(page_views)
                ELSE NULL
            END                                                              AS avg_time_on_page,
            COUNT(*)                                                         AS segments
        FROM fact_device_country
        WHERE {where}
        """)

    bounce_query = text("""
        SELECT
            CASE
                WHEN SUM(total_sessions) > 0
                THEN SUM(bounce_sessions)::NUMERIC / SUM(total_sessions)
                ELSE NULL
            END AS overall_bounce_rate
        FROM fact_bounce_rate
        WHERE dt = :dt
        """)

    with get_session() as session:
        row = session.execute(query, params).one()
        if row.segments == 0:
            return jsonify({"error": f"no data for the given filters on {dt.isoformat()}"}), 404
        bounce_row = session.execute(bounce_query, {"dt": dt_str}).one()

    return jsonify(
        {
            "date": dt.isoformat(),
            "country": country,
            "device": device,
            "total_sessions": int(row.total_sessions or 0),
            "total_page_views": int(row.total_page_views or 0),
            "avg_time_on_page": (
                float(row.avg_time_on_page) if row.avg_time_on_page is not None else None
            ),
            "overall_bounce_rate": (
                float(bounce_row.overall_bounce_rate)
                if bounce_row.overall_bounce_rate is not None
                else None
            ),
        }
    )
