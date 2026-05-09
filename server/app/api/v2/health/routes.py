from flask import Blueprint, jsonify

bp = Blueprint("health_v2", __name__, url_prefix="/api/v2")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
