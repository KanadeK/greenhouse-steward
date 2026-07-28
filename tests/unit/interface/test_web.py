"""FastAPI dashboard and API tests for data, states, and browser boundaries."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from greenhouse_steward.application import GreenhouseApplication
from greenhouse_steward.web import create_web_app


def test_dashboard_is_local_accessible_and_security_hardened(
    facade: GreenhouseApplication,
) -> None:
    """The empty state renders without remote dependencies or missing landmarks."""

    client = TestClient(create_web_app(facade))

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'href="#main-content"' in response.text
    assert "<caption>" not in response.text
    assert "No analysis selected" in response.text
    assert 'value="tomato" selected' in response.text
    assert "https://" not in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.cookies.get("greenhouse_csrf")


def test_html_csrf_origin_validation_and_error_pages(
    facade: GreenhouseApplication,
) -> None:
    """Unsafe browser requests fail explicitly while 404 and 422 remain useful HTML."""

    client = TestClient(create_web_app(facade))
    client.get("/dashboard")

    csrf_failure = client.post(
        "/analyses/sample",
        data={
            "csrf_token": "wrong",
            "sample_slug": "tomato-7d",
            "profile_slug": "tomato",
        },
    )
    assert csrf_failure.status_code == 403
    assert "invalid or missing CSRF token" in csrf_failure.text

    cross_origin = client.post(
        "/api/v1/analyses/sample",
        headers={"Origin": "https://example.invalid"},
        json={"sample_slug": "tomato-7d", "profile_slug": "tomato"},
    )
    assert cross_origin.status_code == 403
    assert cross_origin.headers["content-type"].startswith("application/problem+json")

    same_origin_with_root_path = client.post(
        "/api/v1/analyses/sample",
        headers={"Origin": "http://testserver/"},
        json={"sample_slug": "tomato-7d", "profile_slug": "tomato"},
    )
    assert same_origin_with_root_path.status_code == 201

    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert "Page not found" in missing.text

    invalid_query = client.get("/dashboard?analysis_mode=wrong")
    assert invalid_query.status_code == 422
    assert "Input could not be processed" in invalid_query.text


def test_csv_form_and_api_expose_persisted_analysis(
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """HTML and JSON transports operate on the same real stored observations."""

    client = TestClient(create_web_app(facade))
    client.get("/dashboard")
    csrf_token = client.cookies["greenhouse_csrf"]

    form_response = client.post(
        "/analyses/csv",
        data={
            "csrf_token": csrf_token,
            "device_id": "web-01",
            "profile_slug": "tomato",
            "analysis_mode": "historical",
        },
        files={"csv_file": ("web.csv", dry_csv, "text/csv")},
        follow_redirects=False,
    )
    assert form_response.status_code == 303
    assert "device_id=web-01" in form_response.headers["location"]

    dashboard = client.get(form_response.headers["location"])
    assert dashboard.status_code == 200
    assert "Rule evidence" in dashboard.text
    assert "<caption>" in dashboard.text
    assert "Historical replay" in dashboard.text
    assert "Disabled for historical replay" in dashboard.text

    health = client.get("/api/v1/health")
    assert health.json() == {
        "status": "ok",
        "version": "0.1.0",
        "hardware_control": False,
    }
    assert {item["slug"] for item in client.get("/api/v1/profiles").json()} == {
        "herb",
        "tomato",
    }
    status = client.get(
        "/api/v1/status/web-01",
        params={"profile_slug": "tomato", "analysis_mode": "historical"},
    )
    assert status.status_code == 200
    assert status.json()["history_snapshot_count"] == 2
    assert client.get("/api/v1/export/web-01.csv").text.startswith("timestamp,")

    relay = client.post(
        "/api/v1/relay/simulations",
        json={
            "device_id": "web-01",
            "profile_slug": "tomato",
            "analysis_mode": "historical",
            "requested_seconds": 10,
        },
    )
    assert relay.status_code == 409
    assert relay.json()["type"].endswith("relay-safety")

    missing_relay = client.post(
        "/api/v1/relay/simulations",
        json={
            "device_id": "missing-device",
            "profile_slug": "tomato",
            "analysis_mode": "live",
            "requested_seconds": 10,
        },
    )
    assert missing_relay.status_code == 404

    csrf_token = client.cookies["greenhouse_csrf"]
    missing_relay_page = client.post(
        "/relay/simulations",
        data={
            "csrf_token": csrf_token,
            "device_id": "missing-device",
            "profile_slug": "tomato",
            "analysis_mode": "live",
            "requested_seconds": 10,
        },
    )
    assert missing_relay_page.status_code == 404


def test_api_csv_upload_and_size_limit(
    facade: GreenhouseApplication,
    dry_csv: bytes,
) -> None:
    """The API accepts canonical CSV and rejects oversized bodies before parsing."""

    client = TestClient(create_web_app(facade))
    created = client.post(
        "/api/v1/analyses/csv",
        data={
            "device_id": "api-01",
            "profile_slug": "tomato",
            "analysis_mode": "historical",
        },
        files={"csv_file": ("api.csv", dry_csv, "text/csv")},
    )
    assert created.status_code == 201
    assert created.json()["storage"]["inserted"] == 2

    oversized = client.post(
        "/api/v1/analyses/csv",
        data={"device_id": "api-big"},
        files={
            "csv_file": (
                "too-large.csv",
                b"x" * (10 * 1024 * 1024 + 1),
                "text/csv",
            )
        },
    )
    assert oversized.status_code == 413
    assert oversized.headers["content-type"].startswith("application/problem+json")


def test_styles_preserve_320px_layout_without_gradients() -> None:
    """The local stylesheet includes the compact breakpoint and flat palette."""

    stylesheet = (
        Path(__file__).parents[3]
        / "src"
        / "greenhouse_steward"
        / "web"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")

    assert "min-width: 320px" in stylesheet
    assert "@media (max-width: 640px)" in stylesheet
    assert "linear-gradient" not in stylesheet
