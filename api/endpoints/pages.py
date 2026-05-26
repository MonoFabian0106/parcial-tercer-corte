"""GET /pages/top — top pages by bounce_rate or time_on_page."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from api.db import get_session
from api.validators import ValidationError, parse_date, parse_enum, parse_int

bp = Blueprint("pages", __name__, url_prefix="/pages")

_METRIC_TIME = "time_on_page"
_METRIC_BOUNCE = "bounce_rate"
_ALLOWED_METRICS = {_METRIC_TIME, _METRIC_BOUNCE}


@bp.get("/top")
def top_pages():
    try:
        metric = parse_enum(request.args.get("metric"), _ALLOWED_METRICS, field="metric")
        dt = parse_date(request.args.get("date"))
        limit = parse_int(
            request.args.get("limit"), field="limit", default=10, minimum=1, maximum=100
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    if metric == _METRIC_TIME:
        query = text("""
            SELECT page_url, page_type, views, avg_time_on_page, p95_time_on_page
            FROM fact_top_pages
            WHERE dt = :dt
            ORDER BY avg_time_on_page DESC NULLS LAST
            LIMIT :limit
            """)
        row_to_dict = lambda r: {  # noqa: E731
            "page_url": r.page_url,
            "page_type": r.page_type,
            "views": r.views,
            "avg_time_on_page": (
                float(r.avg_time_on_page) if r.avg_time_on_page is not None else None
            ),
            "p95_time_on_page": (
                float(r.p95_time_on_page) if r.p95_time_on_page is not None else None
            ),
        }
    else:
        query = text("""
            SELECT landing_page_type, total_sessions, bounce_sessions, bounce_rate
            FROM fact_bounce_rate
            WHERE dt = :dt
            ORDER BY bounce_rate DESC
            LIMIT :limit
            """)
        row_to_dict = lambda r: {  # noqa: E731
            "landing_page_type": r.landing_page_type,
            "total_sessions": r.total_sessions,
            "bounce_sessions": r.bounce_sessions,
            "bounce_rate": float(r.bounce_rate),
        }

    with get_session() as session:
        rows = session.execute(query, {"dt": dt.isoformat(), "limit": limit}).all()

    if not rows:
        return jsonify({"error": f"no data for date {dt.isoformat()}"}), 404

    return jsonify(
        {
            "metric": metric,
            "date": dt.isoformat(),
            "limit": limit,
            "results": [row_to_dict(r) for r in rows],
        }
    )
