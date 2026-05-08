import uuid

from flask import g, request


REQUEST_ID_HEADER = "X-Request-ID"


def register_request_id_middleware(app):
    @app.before_request
    def attach_request_id():
        g.request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))

    @app.after_request
    def add_request_id_header(response):
        response.headers[REQUEST_ID_HEADER] = g.get("request_id", "")
        return response
