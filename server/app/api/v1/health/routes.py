from flask import Blueprint, jsonify

bp = Blueprint("health", __name__, url_prefix="")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
