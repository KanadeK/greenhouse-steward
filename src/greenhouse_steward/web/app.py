"""FastAPI routes, security defaults, and server-rendered dashboard."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from greenhouse_steward.application import (
    AnalysisMode,
    AnalysisNotFoundError,
    ApplicationError,
    ApplicationInputError,
    GreenhouseApplication,
    RelaySafetyError,
    report_to_dict,
)
from greenhouse_steward.web.presentation import trend_plot_json

_WEB_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_ROOT / "templates"))
_UPLOAD_LIMIT = 10 * 1024 * 1024
_CSRF_COOKIE = "greenhouse_csrf"


class SampleRequest(BaseModel):
    """JSON request for deterministic sample analysis."""

    model_config = ConfigDict(extra="forbid")

    sample_slug: str = "tomato-7d"
    profile_slug: str = "tomato"


class RelayRequest(BaseModel):
    """JSON request for a simulator transition."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    profile_slug: str = "tomato"
    analysis_mode: AnalysisMode = AnalysisMode.LIVE
    requested_seconds: int = Field(ge=1, le=86_400)


def create_web_app(facade: GreenhouseApplication) -> FastAPI:
    """Create a loopback-oriented app around one shared application facade."""

    app = FastAPI(
        title="Greenhouse Steward",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.greenhouse_application = facade
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(_WEB_ROOT / "static")),
        name="static",
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        origin = request.headers.get("origin")
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and origin is not None
            and not _same_origin(request, origin)
        ):
            error = ApplicationInputError("cross-origin state-changing requests are forbidden")
            response = (
                _problem(error, 403)
                if _is_api_request(request)
                else _html_error(
                    request,
                    status_code=403,
                    title="Request blocked",
                    detail=str(error),
                )
            )
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request,
        _error: RequestValidationError,
    ) -> Response:
        error = ApplicationInputError("request fields are missing or use an invalid value")
        if _is_api_request(request):
            return _problem(error, 422)
        return _html_error(
            request,
            status_code=422,
            title="Input could not be processed",
            detail=str(error),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> Response:
        detail = str(error.detail)
        if _is_api_request(request):
            return _problem(ApplicationInputError(detail), error.status_code)
        return _html_error(
            request,
            status_code=error.status_code,
            title=_http_error_title(error.status_code),
            detail=detail,
        )

    @app.exception_handler(ApplicationError)
    async def application_error(
        request: Request,
        error: ApplicationError,
    ) -> Response:
        status_code = _status_for_application_error(error)
        if _is_api_request(request):
            return _problem(error, status_code)
        return _html_error(
            request,
            status_code=status_code,
            title=_http_error_title(status_code),
            detail=str(error),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _error: Exception) -> Response:
        error = ApplicationError("an unexpected server error occurred")
        if _is_api_request(request):
            return _problem(error, 500)
        return _html_error(
            request,
            status_code=500,
            title="Server error",
            detail=str(error),
        )

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(
        request: Request,
        device_id: Annotated[str | None, Query()] = None,
        profile_slug: Annotated[str, Query()] = "tomato",
        analysis_mode: Annotated[AnalysisMode, Query()] = AnalysisMode.HISTORICAL,
    ) -> Response:
        report: dict[str, object] | None = None
        error: str | None = None
        if device_id:
            try:
                report = report_to_dict(
                    facade.status(
                        device_id,
                        profile_slug=profile_slug,
                        mode=analysis_mode,
                    )
                )
            except ApplicationError as caught:
                error = str(caught)
        return _dashboard_response(
            request,
            facade=facade,
            report=report,
            error=error,
            status_code=200,
        )

    @app.post("/analyses/sample", include_in_schema=False)
    async def analyze_sample_form(
        request: Request,
        csrf_token: Annotated[str, Form()],
        sample_slug: Annotated[str, Form()],
        profile_slug: Annotated[str, Form()],
    ) -> Response:
        _verify_csrf(request, csrf_token)
        try:
            report = facade.analyze_sample(
                sample_slug=sample_slug,
                profile_slug=profile_slug,
            )
        except ApplicationError as error:
            return _dashboard_response(
                request,
                facade=facade,
                report=None,
                error=str(error),
                status_code=422,
            )
        return _dashboard_redirect(report_to_dict(report))

    @app.post("/analyses/csv", include_in_schema=False)
    async def analyze_csv_form(
        request: Request,
        csrf_token: Annotated[str, Form()],
        csv_file: Annotated[UploadFile, File()],
        device_id: Annotated[str, Form()],
        profile_slug: Annotated[str, Form()],
        analysis_mode: Annotated[AnalysisMode, Form()],
    ) -> Response:
        _verify_csrf(request, csrf_token)
        payload = await csv_file.read(_UPLOAD_LIMIT + 1)
        if len(payload) > _UPLOAD_LIMIT:
            return _dashboard_response(
                request,
                facade=facade,
                report=None,
                error="CSV upload exceeds the 10 MiB limit",
                status_code=413,
            )
        try:
            report = facade.analyze_csv(
                payload,
                device_id=device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
                source_name=csv_file.filename or "upload.csv",
            )
        except ApplicationError as error:
            return _dashboard_response(
                request,
                facade=facade,
                report=None,
                error=str(error),
                status_code=422,
            )
        return _dashboard_redirect(report_to_dict(report))

    @app.post("/relay/simulations", include_in_schema=False)
    async def relay_form(
        request: Request,
        csrf_token: Annotated[str, Form()],
        device_id: Annotated[str, Form()],
        profile_slug: Annotated[str, Form()],
        analysis_mode: Annotated[AnalysisMode, Form()],
        requested_seconds: Annotated[int, Form(ge=1, le=86_400)],
    ) -> Response:
        _verify_csrf(request, csrf_token)
        try:
            facade.simulate_relay(
                device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
                requested_seconds=requested_seconds,
            )
        except ApplicationError as error:
            report = _safe_status_dict(
                facade,
                device_id=device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
            )
            return _dashboard_response(
                request,
                facade=facade,
                report=report,
                error=str(error),
                status_code=_status_for_application_error(error),
            )
        return _dashboard_redirect(
            {
                "device_id": device_id,
                "profile_slug": profile_slug,
                "analysis_mode": analysis_mode.value,
            }
        )

    @app.get("/exports/{device_id}.json", include_in_schema=False)
    async def export_json_page(
        request: Request,
        device_id: str,
        profile_slug: Annotated[str, Query()] = "tomato",
        analysis_mode: Annotated[AnalysisMode, Query()] = AnalysisMode.HISTORICAL,
    ) -> Response:
        try:
            payload = facade.export_json(
                device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
            )
        except ApplicationError as error:
            return _html_error(
                request,
                status_code=404,
                title="Export not found",
                detail=str(error),
            )
        return Response(
            payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{device_id}-status.json"'},
        )

    @app.get("/exports/{device_id}.csv", include_in_schema=False)
    async def export_csv_page(request: Request, device_id: str) -> Response:
        try:
            payload = facade.export_csv(device_id)
        except ApplicationError as error:
            return _html_error(
                request,
                status_code=404,
                title="Export not found",
                detail=str(error),
            )
        return Response(
            payload,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{device_id}-readings.csv"'},
        )

    @app.get("/api/v1/health")
    async def api_health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": "0.1.0",
            "hardware_control": False,
        }

    @app.get("/api/v1/profiles")
    async def api_profiles() -> tuple[dict[str, object], ...]:
        return facade.list_profiles()

    @app.post("/api/v1/analyses/sample", status_code=201)
    async def api_analyze_sample(body: SampleRequest) -> Response:
        try:
            report = facade.analyze_sample(
                sample_slug=body.sample_slug,
                profile_slug=body.profile_slug,
            )
        except ApplicationError as error:
            return _problem(error, 422)
        return JSONResponse(report_to_dict(report), status_code=201)

    @app.post("/api/v1/analyses/csv", status_code=201)
    async def api_analyze_csv(
        csv_file: Annotated[UploadFile, File()],
        device_id: Annotated[str, Form()],
        profile_slug: Annotated[str, Form()] = "tomato",
        analysis_mode: Annotated[AnalysisMode, Form()] = AnalysisMode.HISTORICAL,
    ) -> Response:
        payload = await csv_file.read(_UPLOAD_LIMIT + 1)
        if len(payload) > _UPLOAD_LIMIT:
            return _problem(
                ApplicationInputError("CSV upload exceeds the 10 MiB limit"),
                413,
            )
        try:
            report = facade.analyze_csv(
                payload,
                device_id=device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
                source_name=csv_file.filename or "upload.csv",
            )
        except ApplicationError as error:
            return _problem(error, 422)
        return JSONResponse(report_to_dict(report), status_code=201)

    @app.get("/api/v1/status/{device_id}")
    async def api_status(
        device_id: str,
        profile_slug: Annotated[str, Query()] = "tomato",
        analysis_mode: Annotated[AnalysisMode, Query()] = AnalysisMode.HISTORICAL,
    ) -> Response:
        try:
            report = facade.status(
                device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
            )
        except AnalysisNotFoundError as error:
            return _problem(error, 404)
        except ApplicationError as error:
            return _problem(error, 422)
        return JSONResponse(report_to_dict(report))

    @app.get("/api/v1/export/{device_id}.json")
    async def api_export_json(
        device_id: str,
        profile_slug: Annotated[str, Query()] = "tomato",
        analysis_mode: Annotated[AnalysisMode, Query()] = AnalysisMode.HISTORICAL,
    ) -> Response:
        try:
            payload = facade.export_json(
                device_id,
                profile_slug=profile_slug,
                mode=analysis_mode,
            )
        except ApplicationError as error:
            return _problem(error, 404)
        return Response(payload, media_type="application/json")

    @app.get("/api/v1/export/{device_id}.csv")
    async def api_export_csv(device_id: str) -> Response:
        try:
            payload = facade.export_csv(device_id)
        except ApplicationError as error:
            return _problem(error, 404)
        return Response(payload, media_type="text/csv; charset=utf-8")

    @app.post("/api/v1/relay/simulations", status_code=201)
    async def api_relay(body: RelayRequest) -> Response:
        try:
            snapshot = facade.simulate_relay(
                body.device_id,
                profile_slug=body.profile_slug,
                mode=body.analysis_mode,
                requested_seconds=body.requested_seconds,
            )
        except RelaySafetyError as error:
            return _problem(error, 409)
        except ApplicationError as error:
            return _problem(error, _status_for_application_error(error))
        return JSONResponse(snapshot.model_dump(mode="json"), status_code=201)

    return app


def _dashboard_response(
    request: Request,
    *,
    facade: GreenhouseApplication,
    report: dict[str, object] | None,
    error: str | None,
    status_code: int,
) -> Response:
    """Render every dashboard state with one consistent context."""

    csrf_token = request.cookies.get(_CSRF_COOKIE) or secrets.token_urlsafe(32)
    relay: dict[str, object] | None = None
    if report is not None:
        device_id = report.get("device_id")
        profile_slug = report.get("profile_slug")
        if isinstance(device_id, str) and isinstance(profile_slug, str):
            snapshot = facade.relay_status(device_id, profile_slug=profile_slug)
            relay = None if snapshot is None else snapshot.model_dump(mode="json")
    response = _TEMPLATES.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "profiles": facade.list_profiles(),
            "samples": (
                {"slug": "tomato-7d", "label": "Tomato 7-day sample", "profile": "tomato"},
                {"slug": "herb-7d", "label": "Herb 7-day sample", "profile": "herb"},
            ),
            "report": report,
            "relay": relay,
            "error": error,
            "csrf_token": csrf_token,
            "trend_plot_json": trend_plot_json(report),
        },
        status_code=status_code,
    )
    response.set_cookie(
        _CSRF_COOKIE,
        csrf_token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return response


def _verify_csrf(request: Request, submitted: str) -> None:
    """Enforce a constant-time double-submit token check for HTML mutations."""

    cookie = request.cookies.get(_CSRF_COOKIE)
    if cookie is None or not submitted or not secrets.compare_digest(cookie, submitted):
        raise HTTPException(status_code=403, detail="invalid or missing CSRF token")


def _dashboard_redirect(report: dict[str, object]) -> RedirectResponse:
    """Redirect to a reproducible dashboard status URL."""

    query = urlencode(
        {
            "device_id": str(report["device_id"]),
            "profile_slug": str(report["profile_slug"]),
            "analysis_mode": str(report["analysis_mode"]),
        }
    )
    return RedirectResponse(f"/dashboard?{query}", status_code=303)


def _safe_status_dict(
    facade: GreenhouseApplication,
    *,
    device_id: str,
    profile_slug: str,
    mode: AnalysisMode,
) -> dict[str, object] | None:
    """Best-effort status for an HTML safety rejection page."""

    try:
        return report_to_dict(facade.status(device_id, profile_slug=profile_slug, mode=mode))
    except ApplicationError:
        return None


def _problem(error: Exception, status: int) -> JSONResponse:
    """Return a compact RFC 9457-style problem response."""

    if isinstance(error, RelaySafetyError):
        kind = "relay-safety"
        title = "Relay simulation rejected"
    elif isinstance(error, AnalysisNotFoundError):
        kind = "not-found"
        title = "Analysis not found"
    elif isinstance(error, ApplicationInputError):
        kind = "invalid-input"
        title = "Input could not be processed"
    else:
        kind = "application"
        title = "Request could not be completed"
    return JSONResponse(
        {
            "type": f"urn:greenhouse-steward:error:{kind}",
            "title": title,
            "status": status,
            "detail": str(error),
        },
        status_code=status,
        media_type="application/problem+json",
    )


def _is_api_request(request: Request) -> bool:
    """Identify routes that promise problem+json errors."""

    return request.url.path.startswith("/api/")


def _same_origin(request: Request, raw_origin: str) -> bool:
    """Require an Origin header to match the current trusted HTTP origin."""

    try:
        origin = urlsplit(raw_origin)
        request_port = request.url.port
        origin_port = origin.port
    except ValueError:
        return False
    if origin.username is not None or origin.password is not None:
        return False
    default_port = 443 if request.url.scheme == "https" else 80
    return (
        origin.scheme == request.url.scheme
        and origin.hostname == request.url.hostname
        and (origin_port or default_port) == (request_port or default_port)
        and origin.path in {"", "/"}
        and not origin.query
        and not origin.fragment
    )


def _status_for_application_error(error: ApplicationError) -> int:
    """Map safe application failures to stable HTTP status codes."""

    if isinstance(error, AnalysisNotFoundError):
        return 404
    if isinstance(error, RelaySafetyError):
        return 409
    if isinstance(error, ApplicationInputError):
        return 422
    return 500


def _http_error_title(status_code: int) -> str:
    """Return a concise accessible heading for common response states."""

    return {
        403: "Request blocked",
        404: "Page not found",
        409: "Request conflicts with safety policy",
        413: "Upload too large",
        422: "Input could not be processed",
        500: "Server error",
    }.get(status_code, "Request could not be completed")


def _html_error(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
) -> Response:
    """Render a useful local HTML error without exposing internals."""

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "status_code": status_code,
            "error_title": title,
            "error_detail": detail,
        },
        status_code=status_code,
    )
