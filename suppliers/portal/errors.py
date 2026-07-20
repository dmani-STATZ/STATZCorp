"""Shared error envelope helpers for the supplier portal API."""

from django.http import JsonResponse


def error_response(status, code, message, fields=None):
    payload = {"error": {"code": code, "message": message}}
    if fields is not None:
        payload["error"]["fields"] = fields
    return JsonResponse(payload, status=status)


def bad_request(message, fields=None):
    return error_response(400, "bad_request", message, fields=fields)


def unauthorized(message="Invalid or missing API credentials."):
    return error_response(401, "unauthorized", message)


def forbidden(message, fields=None):
    return error_response(403, "forbidden", message, fields=fields)


def not_found(message="No supplier found for the given cage code."):
    return error_response(404, "not_found", message)


def conflict(message, fields=None):
    return error_response(409, "conflict", message, fields=fields)


def validation_error(message, fields=None):
    return error_response(422, "validation_error", message, fields=fields)


def rate_limited(message="Rate limit exceeded."):
    return error_response(429, "rate_limited", message)


def server_error(message="An unexpected server error occurred."):
    return error_response(500, "server_error", message)


def bad_gateway(message="Email could not be sent."):
    return error_response(502, "bad_gateway", message)
