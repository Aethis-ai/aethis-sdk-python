"""Sync and async HTTP clients for the Aethis public API."""

from __future__ import annotations

from typing import Any, Literal

import httpx

from aethis_sdk._base import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    build_headers,
    build_httpx_kwargs,
    classify_response,
    is_5xx,
    logger,
    unavailable_after_retries,
    validate_base_url,
)
from aethis_sdk.errors import AethisContractViolation, AethisError, AethisTimeout
from aethis_sdk.models import (
    DecideResponse,
    ExplainResponse,
    GenerationCancellationResponse,
    GenerationStatusResponse,
    GraphResponse,
    RateLimit,
    RulebookSchemaResponse,
    RulesetSummary,
    SchemaResponse,
    UsageResponse,
)

DECIDE_PATH = "/api/v1/public/decide"
WHOAMI_PATH = "/api/v1/public/me"
RULESETS_PATH = "/api/v1/public/rulesets"
USAGE_PATH = "/api/v1/public/usage"
PROJECTS_PATH = "/api/v1/public/projects"


def _parse_rate_limit(resp: httpx.Response) -> RateLimit | None:
    """Parse the X-RateLimit-* budget headers (epic #552) from a response, or
    None when the server didn't send them (unauthenticated / non-metered)."""
    cls = resp.headers.get("X-RateLimit-Class")
    if cls is None:
        return None
    try:
        return RateLimit(
            operation_class=cls,
            limit=int(resp.headers["X-RateLimit-Limit"]),
            remaining=int(resp.headers["X-RateLimit-Remaining"]),
            reset=int(resp.headers["X-RateLimit-Reset"]),
        )
    except (KeyError, ValueError):
        return None


def _schema_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/schema"


def _graph_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/graph"


def _rulebook_schema_path(rulebook_id: str) -> str:
    return f"/api/v1/public/rulebooks/{rulebook_id}/schema"


def _explain_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/explain"


def _source_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/source"


def _explain_failure_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/explain-failure"


def _generation_status_path(project_id: str) -> str:
    return f"{PROJECTS_PATH}/{project_id}/status"


def _cancel_generation_path(project_id: str) -> str:
    return f"{PROJECTS_PATH}/{project_id}/generate/cancel"


def _is_exact_cancellation_target(status: GenerationStatusResponse, job_id: str) -> bool:
    """Accept a live target or the exact cancelled row for response-loss replay."""

    job = status.job
    if job is None or job.job_id != job_id:
        return False
    if job.status in ("queued", "running"):
        return True
    return (
        job.status == "failed"
        and isinstance(job.error_detail, dict)
        and job.error_detail.get("reason_code") == "generation_cancelled"
    )


def _decide_payload(
    ruleset_id: str,
    field_values: dict[str, Any],
    include_trace: bool,
    include_explanation: bool,
    include_graph_overlay: bool = False,
) -> dict[str, Any]:
    return {
        "ruleset_id": ruleset_id,
        "field_values": field_values,
        "include_trace": include_trace,
        "include_explanation": include_explanation,
        "include_graph_overlay": include_graph_overlay,
    }


def _decide_rulebook_payload(
    rulebook_id: str,
    field_values: dict[str, Any],
    include_trace: bool,
    include_explanation: bool,
    include_graph_overlay: bool = False,
) -> dict[str, Any]:
    return {
        "rulebook_id": rulebook_id,
        "field_values": field_values,
        "include_trace": include_trace,
        "include_explanation": include_explanation,
        "include_graph_overlay": include_graph_overlay,
    }


def _explain_failure_payload(
    field_values: dict[str, Any],
    expected_outcome: Literal["eligible", "not_eligible", "undetermined"],
    test_name: str,
) -> dict[str, Any]:
    return {
        "field_values": field_values,
        "expected_outcome": expected_outcome,
        "test_name": test_name,
    }


class Aethis:
    """Synchronous client for the Aethis public API.

    Two access boundaries, and the client makes the difference explicit:

    * **Evaluation — no key.** ``decide``, ``list_rulesets``, ``get_schema``,
      ``get_graph`` and ``get_explanation``/``explain`` work anonymously
      against public rulesets during the developer beta.
    * **Authoring — invite only.** Publishing, project and rulebook endpoints,
      ``whoami`` and ``get_source`` require an issued API key. Without one they answer 401, and the SDK
      raises :class:`~aethis_sdk.errors.AethisAuthError` with
      ``boundary == "authoring"`` and the access-request link in the message.

    Usage::

        # Evaluation only — no key required
        with Aethis() as client:
            response = client.decide("aethis/construction-all-risks", {...})
            print(response.decision)

        # Authoring (publishing rulesets) — invite-only key
        with Aethis(api_key="ak_live_...") as client:
            ...
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        iam_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = validate_base_url(base_url, is_test=transport is not None)
        self._headers = build_headers(api_key, iam_token)
        self._last_rate_limit: RateLimit | None = None
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.Client | None = None

    def __enter__(self) -> "Aethis":
        self._client = httpx.Client(**build_httpx_kwargs(self._base_url, self._headers, self._timeout, self._transport))
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # Public API --------------------------------------------------------

    def decide(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
        include_explanation: bool = False,
        include_graph_overlay: bool = False,
    ) -> DecideResponse:
        """Evaluate a ruleset against the supplied field values.

        Set ``include_explanation=True`` to populate ``DecideResponse.explanation``
        with the layered, criterion-by-criterion breakdown of the decision.

        Set ``include_graph_overlay=True`` to populate ``DecideResponse.graph_overlay``
        with this decision's status stamped onto the ruleset's dependency graph
        (same node/edge shape as :meth:`get_graph`) — useful for rendering "which
        criteria passed" directly on the ruleset map.
        """
        resp = self._request(
            "POST",
            DECIDE_PATH,
            json=_decide_payload(ruleset_id, field_values, include_trace, include_explanation, include_graph_overlay),
        )
        return DecideResponse.model_validate(resp.json())

    def decide_rulebook(
        self,
        rulebook_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
        include_explanation: bool = False,
        include_graph_overlay: bool = False,
    ) -> DecideResponse:
        """Evaluate a composed rulebook against the supplied field values.

        A rulebook composes multiple rulesets and applies an ``outcome_logic``
        expression across them. ``rulebook_id`` may be either an opaque
        ``rb_<id>`` or a slug (e.g. ``aethis/uk-fsm``); the same shape applies
        whether the slug is single- or multi-segment.

        Unlike :meth:`decide`, rulebook evaluation is always scope-gated —
        anonymous callers get an HTTP 401. Supply ``api_key=...`` when
        constructing the client.

        Set ``include_graph_overlay=True`` to populate ``DecideResponse.graph_overlay``
        — see :meth:`decide`.
        """
        resp = self._request(
            "POST",
            DECIDE_PATH,
            json=_decide_rulebook_payload(
                rulebook_id, field_values, include_trace, include_explanation, include_graph_overlay
            ),
        )
        return DecideResponse.model_validate(resp.json())

    def list_rulesets(self, limit: int = 20, offset: int = 0) -> list[RulesetSummary]:
        """List available rulesets from the public catalogue.

        Anonymous callers see only public rulesets; passing ``api_key=...`` to
        the client additionally surfaces that key's own rulesets. ``limit`` is
        clamped by the engine to 1-50; ``offset`` paginates.
        """
        resp = self._request("GET", RULESETS_PATH, params={"limit": limit, "offset": offset})
        return [RulesetSummary.model_validate(item) for item in resp.json()]

    @property
    def rate_limit(self) -> RateLimit | None:
        """The ``X-RateLimit-*`` budget from the most recent response (epic #552),
        or None if the server sent none. Read after any call to see remaining
        budget for that call's operation class."""
        return self._last_rate_limit

    def usage(self) -> UsageResponse:
        """Return the per-operation-class rate-limit budget for the calling key.

        ``generate`` (LLM rule generation) is the scarce class; ``read`` is
        effectively unlimited-but-metered. Requires an API key.
        """
        resp = self._request("GET", USAGE_PATH)
        return UsageResponse.model_validate(resp.json())

    def get_generation_status(self, project_id: str) -> GenerationStatusResponse:
        """Return the latest generation lifecycle state for ``project_id``.

        This is an observational read: it does not poll, retry, resume, or
        cancel a generation. When there is no generation job, ``response.job``
        is ``None``. Requires an API key with ``projects:read``.
        """
        resp = self._request("GET", _generation_status_path(project_id))
        return GenerationStatusResponse.model_validate(resp.json())

    def cancel_generation(self, project_id: str, job_id: str) -> GenerationCancellationResponse:
        """Request cooperative cancellation of the observed generation job.

        This explicit, destructive action marks the job failed and releases
        project ownership only when ``job_id`` still names that run. It cannot interrupt an in-flight provider request;
        that worker stops at its next safe boundary. Check
        :meth:`get_generation_status` first when deciding whether to cancel.
        Requires an API key with ``projects:write``.
        """
        status = self.get_generation_status(project_id)
        if status.generation_contract_version != 1:
            raise AethisContractViolation(
                "Generation cancellation requires an engine advertising generation_contract_version=1."
            )
        if not _is_exact_cancellation_target(status, job_id):
            raise AethisContractViolation(
                "The exact generation job is neither active nor an already-cancelled replay target."
            )
        resp = self._request("POST", _cancel_generation_path(project_id), params={"job_id": job_id})
        return GenerationCancellationResponse.model_validate(resp.json())

    def get_schema(self, ruleset_id: str) -> SchemaResponse:
        """Return the field schema for a ruleset."""
        resp = self._request("GET", _schema_path(ruleset_id))
        return SchemaResponse.model_validate(resp.json())

    def get_graph(self, ruleset_id: str) -> GraphResponse:
        """Return the field -> criterion -> group -> outcome dependency graph for a
        ruleset, plus a rendered Mermaid diagram. Public rulesets can be inspected
        without an API key, same as :meth:`get_schema`.
        """
        resp = self._request("GET", _graph_path(ruleset_id))
        return GraphResponse.model_validate(resp.json())

    def get_rulebook_schema(self, rulebook_id: str) -> RulebookSchemaResponse:
        """Return the combined field schema for a rulebook's composed rulesets,
        plus its conversational-agent ``robot_hints`` and ``engine_version``.

        Unlike :meth:`get_schema`, rulebook schema is always scope-gated —
        anonymous callers get an HTTP 401. Supply ``api_key=...`` when
        constructing the client.
        """
        resp = self._request("GET", _rulebook_schema_path(rulebook_id))
        return RulebookSchemaResponse.model_validate(resp.json())

    def whoami(self) -> dict[str, Any]:
        """Return metadata about the current API key."""
        resp = self._request("GET", WHOAMI_PATH)
        return resp.json()

    def get_explanation(self, ruleset_id: str) -> ExplainResponse:
        """Return the typed explanation of a ruleset's rules.

        The response carries the resolved immutable identity of the content it
        describes (:meth:`ExplainResponse.require_content_identity`) and typed
        :class:`~aethis_sdk.models.SourceReference` citations per criterion.

        Note the shape difference between the two explanation surfaces: this
        endpoint returns a **flat** ``criteria`` list, whereas ``decide(...,
        include_explanation=True)`` nests criteria under
        ``explanation.groups[].criteria[]``. They share the ``SourceReference``
        DTO, not the envelope.
        """
        resp = self._request("GET", _explain_path(ruleset_id))
        return ExplainResponse.model_validate(resp.json())

    def explain(self, ruleset_id: str) -> dict[str, Any]:
        """Return a human-readable explanation of a ruleset's rules, as the raw
        decoded JSON body.

        Prefer :meth:`get_explanation`, which returns the same payload typed —
        including resolved identity and :class:`SourceReference` objects. This
        method stays for callers already indexing the raw dict.
        """
        resp = self._request("GET", _explain_path(ruleset_id))
        return resp.json()

    def get_source(self, ruleset_id: str) -> dict[str, Any]:
        """Return the source-text provenance for a ruleset.

        **Key-required, and not part of the no-key evaluation surface.** This
        endpoint is gated behind a scope that is not granted to external keys,
        so an anonymous call answers 401 regardless of the ruleset's
        visibility. For published citations, use :meth:`get_explanation`, which
        is anonymous on a public ruleset and returns the same
        :class:`~aethis_sdk.models.SourceReference` DTO.
        """
        resp = self._request("GET", _source_path(ruleset_id))
        return resp.json()

    def explain_failure(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        expected_outcome: Literal["eligible", "not_eligible", "undetermined"],
        test_name: str = "test",
    ) -> dict[str, Any]:
        """Diagnose a failing /decide for a ruleset, returning the criterion that
        failed and a targeted fix hint.

        `ruleset_id` must be the concrete identifier (not a slug) — the
        underlying endpoint does not currently resolve slugs. Pull it from the
        `ruleset_id` field on the `DecideResponse` you got back from `decide()`.

        `expected_outcome` is what you thought the decision *should* have been:
        one of `"eligible"`, `"not_eligible"`, or `"undetermined"`.
        """
        resp = self._request(
            "POST",
            _explain_failure_path(ruleset_id),
            json=_explain_failure_payload(field_values, expected_outcome, test_name),
        )
        return resp.json()

    # Internal ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Client is not open. Use 'with Aethis(...) as client:'.")

        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as e:
                logger.error("Timeout on %s %s: %s", method, path, e)
                raise AethisTimeout("Aethis API request timed out") from e
            except httpx.HTTPError as e:
                logger.error("HTTP error on %s %s: %s", method, path, e)
                raise AethisError("Aethis API connection error") from e

            if not is_5xx(resp):
                classify_response(resp)
                self._last_rate_limit = _parse_rate_limit(resp)
                return resp

            last_status = resp.status_code
            logger.warning(
                "Aethis API %d on %s (attempt %d/%d)",
                resp.status_code,
                path,
                attempt + 1,
                MAX_RETRIES + 1,
            )

        raise unavailable_after_retries(last_status or 500, MAX_RETRIES + 1)


class AsyncAethis:
    """Asynchronous client for the Aethis public API.

    Same two access boundaries as :class:`Aethis` — evaluation needs no key,
    authoring is invite-only — and the same typed models on every path.

    Usage::

        # Evaluation only — no key required
        async with AsyncAethis() as client:
            response = await client.decide("aethis/construction-all-risks", {...})
            print(response.decision)

        # Authoring (publishing rulesets) — invite-only key
        async with AsyncAethis(api_key="ak_live_...") as client:
            ...
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        iam_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = validate_base_url(base_url, is_test=transport is not None)
        self._headers = build_headers(api_key, iam_token)
        self._last_rate_limit: RateLimit | None = None
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AsyncAethis":
        self._client = httpx.AsyncClient(
            **build_httpx_kwargs(self._base_url, self._headers, self._timeout, self._transport)
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # Public API --------------------------------------------------------

    async def decide(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
        include_explanation: bool = False,
        include_graph_overlay: bool = False,
    ) -> DecideResponse:
        """Evaluate a ruleset against the supplied field values.

        Set ``include_explanation=True`` to populate ``DecideResponse.explanation``
        with the layered, criterion-by-criterion breakdown of the decision.

        Set ``include_graph_overlay=True`` to populate ``DecideResponse.graph_overlay``
        — see :meth:`Aethis.decide`.
        """
        resp = await self._request(
            "POST",
            DECIDE_PATH,
            json=_decide_payload(ruleset_id, field_values, include_trace, include_explanation, include_graph_overlay),
        )
        return DecideResponse.model_validate(resp.json())

    async def decide_rulebook(
        self,
        rulebook_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
        include_explanation: bool = False,
        include_graph_overlay: bool = False,
    ) -> DecideResponse:
        """Evaluate a composed rulebook against the supplied field values.

        Async counterpart to :meth:`Aethis.decide_rulebook`. Rulebook
        evaluation requires an API key — anonymous callers get HTTP 401.

        Set ``include_graph_overlay=True`` to populate ``DecideResponse.graph_overlay``
        — see :meth:`Aethis.decide`.
        """
        resp = await self._request(
            "POST",
            DECIDE_PATH,
            json=_decide_rulebook_payload(
                rulebook_id, field_values, include_trace, include_explanation, include_graph_overlay
            ),
        )
        return DecideResponse.model_validate(resp.json())

    async def list_rulesets(self, limit: int = 20, offset: int = 0) -> list[RulesetSummary]:
        """List available rulesets from the public catalogue.

        Async counterpart to :meth:`Aethis.list_rulesets`.
        """
        resp = await self._request("GET", RULESETS_PATH, params={"limit": limit, "offset": offset})
        return [RulesetSummary.model_validate(item) for item in resp.json()]

    @property
    def rate_limit(self) -> RateLimit | None:
        """The ``X-RateLimit-*`` budget from the most recent response (epic #552),
        or None if the server sent none."""
        return self._last_rate_limit

    async def usage(self) -> UsageResponse:
        """Return the per-operation-class rate-limit budget for the calling key.

        ``generate`` is the scarce class; ``read`` is effectively unlimited-but-
        metered. Requires an API key.
        """
        resp = await self._request("GET", USAGE_PATH)
        return UsageResponse.model_validate(resp.json())

    async def get_generation_status(self, project_id: str) -> GenerationStatusResponse:
        """Return the latest generation lifecycle state for ``project_id``.

        This is an observational read: it does not poll, retry, resume, or
        cancel a generation. Requires an API key with ``projects:read``.
        """
        resp = await self._request("GET", _generation_status_path(project_id))
        return GenerationStatusResponse.model_validate(resp.json())

    async def cancel_generation(self, project_id: str, job_id: str) -> GenerationCancellationResponse:
        """Request cooperative cancellation of the observed generation job.

        This method is explicit and destructive. It cannot interrupt an
        in-flight provider request; the worker stops at its next safe boundary.
        Requires an API key with ``projects:write``.
        """
        status = await self.get_generation_status(project_id)
        if status.generation_contract_version != 1:
            raise AethisContractViolation(
                "Generation cancellation requires an engine advertising generation_contract_version=1."
            )
        if not _is_exact_cancellation_target(status, job_id):
            raise AethisContractViolation(
                "The exact generation job is neither active nor an already-cancelled replay target."
            )
        resp = await self._request("POST", _cancel_generation_path(project_id), params={"job_id": job_id})
        return GenerationCancellationResponse.model_validate(resp.json())

    async def get_schema(self, ruleset_id: str) -> SchemaResponse:
        """Return the field schema for a ruleset."""
        resp = await self._request("GET", _schema_path(ruleset_id))
        return SchemaResponse.model_validate(resp.json())

    async def get_graph(self, ruleset_id: str) -> GraphResponse:
        """Return the field -> criterion -> group -> outcome dependency graph for a
        ruleset, plus a rendered Mermaid diagram. Async counterpart to
        :meth:`Aethis.get_graph`.
        """
        resp = await self._request("GET", _graph_path(ruleset_id))
        return GraphResponse.model_validate(resp.json())

    async def get_rulebook_schema(self, rulebook_id: str) -> RulebookSchemaResponse:
        """Return the combined field schema for a rulebook's composed rulesets,
        plus its conversational-agent ``robot_hints`` and ``engine_version``.
        Async counterpart to :meth:`Aethis.get_rulebook_schema`.
        """
        resp = await self._request("GET", _rulebook_schema_path(rulebook_id))
        return RulebookSchemaResponse.model_validate(resp.json())

    async def whoami(self) -> dict[str, Any]:
        """Return metadata about the current API key."""
        resp = await self._request("GET", WHOAMI_PATH)
        return resp.json()

    async def get_explanation(self, ruleset_id: str) -> ExplainResponse:
        """Return the typed explanation of a ruleset's rules.

        Async counterpart to :meth:`Aethis.get_explanation` — same typed
        :class:`ExplainResponse`, same flat ``criteria`` shape, same
        :class:`~aethis_sdk.models.SourceReference` DTO.
        """
        resp = await self._request("GET", _explain_path(ruleset_id))
        return ExplainResponse.model_validate(resp.json())

    async def explain(self, ruleset_id: str) -> dict[str, Any]:
        """Return a human-readable explanation of a ruleset's rules, as the raw
        decoded JSON body. Prefer :meth:`AsyncAethis.get_explanation`.
        """
        resp = await self._request("GET", _explain_path(ruleset_id))
        return resp.json()

    async def get_source(self, ruleset_id: str) -> dict[str, Any]:
        """Return the source-text provenance for a ruleset.

        Key-required — see :meth:`Aethis.get_source`. Prefer
        :meth:`get_explanation` for anonymous access to published citations.
        """
        resp = await self._request("GET", _source_path(ruleset_id))
        return resp.json()

    async def explain_failure(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        expected_outcome: Literal["eligible", "not_eligible", "undetermined"],
        test_name: str = "test",
    ) -> dict[str, Any]:
        """Diagnose a failing /decide for a ruleset, returning the criterion that
        failed and a targeted fix hint.

        Async counterpart to :meth:`Aethis.explain_failure`.

        `ruleset_id` must be the concrete identifier, not a slug — see
        :meth:`Aethis.explain_failure`.

        `expected_outcome` is what you thought the decision *should* have been:
        one of `"eligible"`, `"not_eligible"`, or `"undetermined"`.
        """
        resp = await self._request(
            "POST",
            _explain_failure_path(ruleset_id),
            json=_explain_failure_payload(field_values, expected_outcome, test_name),
        )
        return resp.json()

    # Internal ----------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Client is not open. Use 'async with AsyncAethis(...) as client:'.")

        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as e:
                logger.error("Timeout on %s %s: %s", method, path, e)
                raise AethisTimeout("Aethis API request timed out") from e
            except httpx.HTTPError as e:
                logger.error("HTTP error on %s %s: %s", method, path, e)
                raise AethisError("Aethis API connection error") from e

            if not is_5xx(resp):
                classify_response(resp)
                self._last_rate_limit = _parse_rate_limit(resp)
                return resp

            last_status = resp.status_code
            logger.warning(
                "Aethis API %d on %s (attempt %d/%d)",
                resp.status_code,
                path,
                attempt + 1,
                MAX_RETRIES + 1,
            )

        raise unavailable_after_retries(last_status or 500, MAX_RETRIES + 1)
