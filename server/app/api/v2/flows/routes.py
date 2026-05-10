from flask import Blueprint, g, jsonify, request

from app.api.v2.flows.service import (
    create_flow,
    create_flow_edge,
    create_flow_node,
    delete_flow,
    delete_flow_edge,
    delete_flow_node,
    duplicate_flow,
    get_flow,
    get_flow_node,
    list_flow_edges,
    list_flow_nodes,
    list_flows,
    publish_flow,
    update_flow,
    update_flow_edge,
    update_flow_node,
    validate_flow,
)
from app.middleware.permissions_v2 import jwt_context_required, require_permission

bp = Blueprint("flows_v2", __name__, url_prefix="/api/v2")


@bp.post("/flows")
@jwt_context_required
@require_permission("businesses.manage")
def create_flow_endpoint():
    payload = request.get_json(silent=True) or {}
    result, error = create_flow(g.actor_user, payload)
    if error:
        status = 404 if error == "Business not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("/flows")
@jwt_context_required
@require_permission("businesses.read")
def list_flows_endpoint():
    result, error = list_flows(
        g.actor_user,
        business_id=request.args.get("business_id"),
        status=request.args.get("status"),
    )
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"items": result}), 200


@bp.get("/flows/<int:flow_id>")
@jwt_context_required
@require_permission("businesses.read")
def get_flow_endpoint(flow_id):
    result, error = get_flow(g.actor_user, flow_id)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.put("/flows/<int:flow_id>")
@jwt_context_required
@require_permission("businesses.manage")
def update_flow_endpoint(flow_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_flow(g.actor_user, flow_id, payload)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/flows/<int:flow_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_flow_endpoint(flow_id):
    result, error = delete_flow(g.actor_user, flow_id)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/flows/<int:flow_id>/validate")
@jwt_context_required
@require_permission("businesses.manage")
def validate_flow_endpoint(flow_id):
    result, error = validate_flow(g.actor_user, flow_id)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/flows/<int:flow_id>/publish")
@jwt_context_required
@require_permission("businesses.manage")
def publish_flow_endpoint(flow_id):
    result, error = publish_flow(g.actor_user, flow_id)
    if error:
        status = (
            404
            if error == "Flow not found"
            else 403
            if "permission" in error.lower()
            else 422
            if error == "Flow validation failed"
            else 400
        )
        payload = {"error": error}
        if error == "Flow validation failed":
            validation, _ = validate_flow(g.actor_user, flow_id)
            payload["validation"] = validation
        return jsonify(payload), status
    return jsonify(result), 200


@bp.post("/flows/<int:flow_id>/duplicate")
@jwt_context_required
@require_permission("businesses.manage")
def duplicate_flow_endpoint(flow_id):
    payload = request.get_json(silent=True) or {}
    result, error = duplicate_flow(g.actor_user, flow_id, payload)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.post("/flows/<int:flow_id>/nodes")
@jwt_context_required
@require_permission("businesses.manage")
def create_flow_node_endpoint(flow_id):
    payload = request.get_json(silent=True) or {}
    result, error = create_flow_node(g.actor_user, flow_id, payload)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("/flows/<int:flow_id>/nodes")
@jwt_context_required
@require_permission("businesses.read")
def list_flow_nodes_endpoint(flow_id):
    result, error = list_flow_nodes(g.actor_user, flow_id)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify({"items": result}), 200


@bp.get("/flow-nodes/<int:node_id>")
@jwt_context_required
@require_permission("businesses.read")
def get_flow_node_endpoint(node_id):
    result, error = get_flow_node(g.actor_user, node_id)
    if error:
        status = 404 if error == "Flow node not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.put("/flow-nodes/<int:node_id>")
@jwt_context_required
@require_permission("businesses.manage")
def update_flow_node_endpoint(node_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_flow_node(g.actor_user, node_id, payload)
    if error:
        status = 404 if error == "Flow node not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/flow-nodes/<int:node_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_flow_node_endpoint(node_id):
    result, error = delete_flow_node(g.actor_user, node_id)
    if error:
        status = 404 if error == "Flow node not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/flows/<int:flow_id>/edges")
@jwt_context_required
@require_permission("businesses.manage")
def create_flow_edge_endpoint(flow_id):
    payload = request.get_json(silent=True) or {}
    result, error = create_flow_edge(g.actor_user, flow_id, payload)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("/flows/<int:flow_id>/edges")
@jwt_context_required
@require_permission("businesses.read")
def list_flow_edges_endpoint(flow_id):
    result, error = list_flow_edges(g.actor_user, flow_id)
    if error:
        status = 404 if error == "Flow not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify({"items": result}), 200


@bp.put("/flow-edges/<int:edge_id>")
@jwt_context_required
@require_permission("businesses.manage")
def update_flow_edge_endpoint(edge_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_flow_edge(g.actor_user, edge_id, payload)
    if error:
        status = 404 if error == "Flow edge not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/flow-edges/<int:edge_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_flow_edge_endpoint(edge_id):
    result, error = delete_flow_edge(g.actor_user, edge_id)
    if error:
        status = 404 if error == "Flow edge not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200
