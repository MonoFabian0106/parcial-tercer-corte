"""GET /anomalies — list anomalous sessions detected for a given date."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from api.db import get_session
from api.validators import ValidationError, parse_date, parse_int

bp = Blueprint("anomalies", __name__, url_prefix="/anomalies")


@bp.get("")
def list_anomalies():
    try:
        dt = parse_date(request.args.get("date"))
        limit = parse_int(
            request.args.get("limit"), field="limit", default=100, minimum=1, maximum=1000
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    query = text("""
        SELECT
            session_id,
            user_id,
            total_events,
            session_duration_seconds,
            unique_pages,
            events_per_minute,
            z_total_events,
            z_session_duration_seconds,
            z_unique_pages,
            z_events_per_minute,
            total_flags,
            anomaly_type
        FROM fact_anomalies
        WHERE dt = :dt
        ORDER BY total_flags DESC NULLS LAST, GREATEST(
            COALESCE(ABS(z_total_events), 0),
            COALESCE(ABS(z_session_duration_seconds), 0),
            COALESCE(ABS(z_unique_pages), 0),
            COALESCE(ABS(z_events_per_minute), 0)
        ) DESC
        LIMIT :limit
        """)

    with get_session() as session:
        rows = session.execute(query, {"dt": dt.isoformat(), "limit": limit}).all()

    if not rows:
        return jsonify({"error": f"no anomalies for date {dt.isoformat()}"}), 404

    def _f(x):
        return float(x) if x is not None else None

    return jsonify(
        {
            "date": dt.isoformat(),
            "limit": limit,
            "count": len(rows),
            "results": [
                {
                    "session_id": r.session_id,
                    "user_id": r.user_id,
                    "total_events": r.total_events,
                    "session_duration_seconds": _f(r.session_duration_seconds),
                    "unique_pages": r.unique_pages,
                    "events_per_minute": _f(r.events_per_minute),
                    "z_score": {
                        "total_events": _f(r.z_total_events),
                        "session_duration_seconds": _f(r.z_session_duration_seconds),
                        "unique_pages": _f(r.z_unique_pages),
                        "events_per_minute": _f(r.z_events_per_minute),
                    },
                    "total_flags": r.total_flags,
                    "anomaly_type": r.anomaly_type,
                }
                for r in rows
            ],
        }
    )
