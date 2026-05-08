from flask import jsonify


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        app.logger.exception("Unhandled exception", exc_info=exc)
        return jsonify({"error": "Internal server error"}), 500
