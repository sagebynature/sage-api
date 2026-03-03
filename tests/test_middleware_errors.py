"""Tests for error handling middleware in Sage API."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from sage_api.middleware.errors import add_exception_handlers


def make_app() -> tuple[FastAPI, TestClient]:
    """Create a minimal FastAPI app with error handlers and test endpoints."""
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/raise-404")
    async def raise_not_found():
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/raise-401-dict")
    async def raise_unauthorized():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Unauthorized",
                "detail": "Invalid or missing API key",
                "status_code": 401,
            },
        )

    @app.get("/raise-404-dict")
    async def raise_not_found_dict():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Not Found",
                "detail": "Agent 'foo' not found",
                "status_code": 404,
            },
        )

    @app.get("/raise-400-dict-no-detail")
    async def raise_bad_request_dict():
        raise HTTPException(
            status_code=400,
            detail={"error": "Bad Request"},
        )

    @app.get("/raise-500")
    async def raise_unhandled():
        raise RuntimeError("boom")

    @app.post("/validate-body")
    async def validate_body(body: dict):
        return body

    # TestClient with raise_server_exceptions=False so unhandled exceptions
    # are processed by our handler rather than re-raised by the test client.
    client = TestClient(app, raise_server_exceptions=False)
    return app, client


@pytest.fixture(scope="module")
def client() -> TestClient:
    _, c = make_app()
    return c


class TestHttpExceptionHandler:
    """Tests for http_exception_handler."""

    def test_404_returns_correct_status(self, client: TestClient):
        """HTTP 404 exception → 404 response."""
        response = client.get("/raise-404")
        assert response.status_code == 404

    def test_404_body_has_error_response_keys(self, client: TestClient):
        """HTTP 404 body contains 'error', 'detail', and 'status_code' keys."""
        response = client.get("/raise-404")
        body = response.json()
        assert "error" in body
        assert "detail" in body
        assert "status_code" in body

    def test_404_body_values(self, client: TestClient):
        """HTTP 404 body has correct values."""
        response = client.get("/raise-404")
        body = response.json()
        assert body["error"] == "Not found"
        assert body["status_code"] == 404

    def test_401_with_dict_detail_extracts_error_key(self, client: TestClient):
        """HTTP 401 with dict detail extracts 'error' key as message."""
        response = client.get("/raise-401-dict")
        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "Unauthorized"
        assert body["status_code"] == 401

    def test_401_dict_detail_does_not_leak_internal_dict(self, client: TestClient):
        """HTTP 401 body does not expose the raw dict as error text."""
        response = client.get("/raise-401-dict")
        body = response.json()
        # error should be a clean string, not a stringified dict
        assert "{" not in body["error"]

    def test_response_is_json(self, client: TestClient):
        """Response content-type is application/json."""
        response = client.get("/raise-404")
        assert "application/json" in response.headers["content-type"]

    def test_string_detail_is_preserved_in_response(self, client: TestClient):
        """HTTP exception with string detail exposes it in 'detail' field."""
        response = client.get("/raise-404")
        body = response.json()
        assert body["detail"] == "Not found"

    def test_401_dict_detail_preserves_detail_field(self, client: TestClient):
        """HTTP 401 with dict detail preserves the 'detail' value from the dict."""
        response = client.get("/raise-401-dict")
        body = response.json()
        assert body["detail"] == "Invalid or missing API key"

    def test_404_dict_detail_preserves_detail_field(self, client: TestClient):
        """HTTP 404 with ErrorResponse-shaped dict preserves the 'detail' value."""
        response = client.get("/raise-404-dict")
        body = response.json()
        assert body["error"] == "Not Found"
        assert body["detail"] == "Agent 'foo' not found"
        assert body["status_code"] == 404

    def test_dict_without_detail_key_returns_null_detail(self, client: TestClient):
        """HTTP exception with dict lacking 'detail' key returns null detail."""
        response = client.get("/raise-400-dict-no-detail")
        body = response.json()
        assert body["error"] == "Bad Request"
        assert body["detail"] is None
        assert body["status_code"] == 400


class TestUnhandledExceptionHandler:
    """Tests for unhandled_exception_handler."""

    def test_unhandled_exception_returns_500(self, client: TestClient):
        """Unhandled RuntimeError → 500 response."""
        response = client.get("/raise-500")
        assert response.status_code == 500

    def test_unhandled_exception_body_keys(self, client: TestClient):
        """500 body contains 'error', 'detail', and 'status_code'."""
        response = client.get("/raise-500")
        body = response.json()
        assert "error" in body
        assert "detail" in body
        assert "status_code" in body

    def test_unhandled_exception_generic_message(self, client: TestClient):
        """500 response uses generic message, not internal exception text."""
        response = client.get("/raise-500")
        body = response.json()
        assert body["error"] == "Internal Server Error"
        assert body["status_code"] == 500

    def test_unhandled_exception_detail_is_null(self, client: TestClient):
        """500 response detail is null (no internal info leaked)."""
        response = client.get("/raise-500")
        body = response.json()
        assert body["detail"] is None

    def test_unhandled_exception_does_not_expose_boom(self, client: TestClient):
        """Internal 'boom' message must not appear in 500 response body."""
        response = client.get("/raise-500")
        assert "boom" not in response.text


class TestValidationExceptionHandler:
    """Tests for validation_exception_handler."""

    def test_missing_required_field_returns_422(self, client: TestClient):
        """RequestValidationError on missing body → 422 response."""
        # POST /validate-body with an invalid payload (non-dict)
        response = client.post("/validate-body", content=b"not-json", headers={"content-type": "application/json"})
        assert response.status_code == 422

    def test_422_body_has_error_response_keys(self, client: TestClient):
        """422 body contains 'error', 'detail', and 'status_code'."""
        response = client.post("/validate-body", content=b"not-json", headers={"content-type": "application/json"})
        body = response.json()
        assert "error" in body
        assert "detail" in body
        assert "status_code" in body

    def test_422_error_message(self, client: TestClient):
        """422 body error field reads 'Validation Error'."""
        response = client.post("/validate-body", content=b"not-json", headers={"content-type": "application/json"})
        body = response.json()
        assert body["error"] == "Validation Error"
        assert body["status_code"] == 422

    def test_422_detail_contains_field_errors(self, client: TestClient):
        """422 detail is non-empty string describing the validation errors."""
        response = client.post("/validate-body", content=b"not-json", headers={"content-type": "application/json"})
        body = response.json()
        assert body["detail"] is not None
        assert len(body["detail"]) > 0


class TestAddExceptionHandlers:
    """Tests for add_exception_handlers utility."""

    def test_add_exception_handlers_registers_handlers(self):
        """add_exception_handlers attaches handlers without error."""
        app = FastAPI()
        # Should not raise
        add_exception_handlers(app)

    def test_handlers_are_callable(self):
        """All three handler functions are callable."""
        from sage_api.middleware.errors import (
            http_exception_handler,
            unhandled_exception_handler,
            validation_exception_handler,
        )

        assert callable(http_exception_handler)
        assert callable(validation_exception_handler)
        assert callable(unhandled_exception_handler)
