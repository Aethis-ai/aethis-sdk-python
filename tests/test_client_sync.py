"""Sync client tests — mirrors the async test surface."""

from __future__ import annotations

import json

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisAPIError,
    AethisUnavailable,
    DecideResponse,
    GenerationCancellationResponse,
    GenerationStatusResponse,
    RulesetSummary,
    SchemaResponse,
)

from tests.conftest import (
    make_decide_response,
    make_ruleset_summary,
    make_schema_response,
)


class TestDecide:
    def test_returns_parsed_response_on_200(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            assert request.url.path == "/api/v1/public/decide"
            body = json.loads(request.content)
            assert body["ruleset_id"] == "test_ruleset:v1"
            assert body["field_values"] == {"age": 25}
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.decide("test_ruleset:v1", {"age": 25})

        assert isinstance(resp, DecideResponse)
        assert resp.decision == "eligible"
        assert call_count == 1

    def test_sends_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "my-secret-key"
            return httpx.Response(200, json=make_decide_response())

        with Aethis(
            api_key="my-secret-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            client.decide("ruleset:v1", {})

    def test_no_api_key_omits_x_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "x-api-key" not in request.headers
            return httpx.Response(200, json=make_decide_response())

        with Aethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.decide("ruleset:v1", {})

    def test_decide_works_without_api_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        with Aethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.decide("aethis/construction-all-risks", {})

        assert resp.decision == "eligible"

    def test_retries_once_on_500_then_succeeds(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500)
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.decide("ruleset:v1", {})

        assert resp.decision == "eligible"
        assert call_count == 2

    def test_raises_unavailable_after_retries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisUnavailable):
                client.decide("ruleset:v1", {})

    def test_404_raises_api_error_with_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Ruleset not found"})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("nonexistent:v1", {})
        assert exc_info.value.status_code == 404


class TestDecideRulebook:
    """Aethis-ai/aethis-sdk-python#14 — rulebook surface on the SDK."""

    def test_sends_rulebook_id_payload(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/decide"
            body = json.loads(request.content)
            assert body == {
                "rulebook_id": "aethis/uk-fsm",
                "field_values": {"child.age": 10},
                "include_trace": False,
                "include_explanation": False,
                "include_graph_overlay": False,
            }
            return httpx.Response(
                200,
                json=make_decide_response(
                    decision="eligible",
                    ruleset_id=None,
                    rulebook_id="rb_kzZ_td0tbKW_OLRB",
                    slug="aethis/uk-fsm",
                ),
            )

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.decide_rulebook("aethis/uk-fsm", {"child.age": 10})

        assert isinstance(resp, DecideResponse)
        assert resp.decision == "eligible"
        assert resp.rulebook_id == "rb_kzZ_td0tbKW_OLRB"
        assert resp.ruleset_id is None

    def test_passes_include_trace_through(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["include_trace"] is True
            return httpx.Response(200, json=make_decide_response(rulebook_id="rb_x"))

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.decide_rulebook("rb_x", {}, include_trace=True)

    def test_accepts_opaque_id_or_slug(self):
        seen_payloads: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_payloads.append(json.loads(request.content))
            return httpx.Response(200, json=make_decide_response())

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.decide_rulebook("rb_kzZ_td0tbKW_OLRB", {})
            client.decide_rulebook("aethis/uk-fsm", {})

        assert seen_payloads[0]["rulebook_id"] == "rb_kzZ_td0tbKW_OLRB"
        assert seen_payloads[1]["rulebook_id"] == "aethis/uk-fsm"


class TestGetSchema:
    def test_returns_parsed_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/b:v1/schema"
            return httpx.Response(200, json=make_schema_response(ruleset_id="b:v1"))

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.get_schema("b:v1")
        assert isinstance(resp, SchemaResponse)
        assert resp.ruleset_id == "b:v1"


class TestGenerationRecovery:
    def test_get_generation_status_is_a_single_observational_read(self):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.method == "GET"
            assert request.url.path == "/api/v1/public/projects/proj_123/status"
            return httpx.Response(
                200,
                json={
                    "project_status": "generating",
                    "latest_ruleset_id": None,
                    "job": {
                        "job_id": "job_123",
                        "status": "running",
                        "progress_percent": 50,
                        "worker_heartbeat_at": "2026-09-02T18:19:45Z",
                        "seconds_since_progress": 4.0,
                    },
                },
            )

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            response = client.get_generation_status("proj_123")

        assert isinstance(response, GenerationStatusResponse)
        assert response.job is not None
        assert response.job.worker_heartbeat_at is not None
        assert calls == 1, "status must never poll or retry a healthy response"

    def test_cancel_generation_is_an_explicit_cooperative_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "generation_contract_version": 1,
                        "telemetry_availability": "current",
                        "retry_readiness": "blocked",
                        "worker_lifecycle": "active",
                        "project_status": "generating",
                        "job": {"job_id": "job_123", "status": "running", "progress_percent": 50},
                        "latest_ruleset_id": None,
                    },
                )
            assert request.method == "POST"
            assert request.url.path == "/api/v1/public/projects/proj_123/generate/cancel"
            assert request.url.params["job_id"] == "job_123"
            assert request.content == b""
            return httpx.Response(
                200,
                json={
                    "job_id": "job_123",
                    "status": "failed",
                    "outcome": "cancelled",
                    "project_released": True,
                    "detail": "The worker observes cancellation at its next boundary.",
                },
            )

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            response = client.cancel_generation("proj_123", "job_123")

        assert isinstance(response, GenerationCancellationResponse)
        assert response.project_released is True


class TestExplainFailure:
    """POST /api/v1/public/rulesets/{ruleset_id}/explain-failure SDK wrapper."""

    def test_happy_path_returns_dict(self):
        expected_response = {
            "failing_criterion": "age >= 18",
            "fix_hint": "Provide a value for 'age' that satisfies the criterion.",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/rs_abc123/explain-failure"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["field_values"] == {"age": 15}
            assert body["expected_outcome"] == "eligible"
            assert body["test_name"] == "test"
            return httpx.Response(200, json=expected_response)

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.explain_failure("rs_abc123", {"age": 15}, "eligible")

        assert resp == expected_response

    def test_default_test_name_is_test(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["test_name"] == "test"
            return httpx.Response(200, json={"failing_criterion": "x"})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.explain_failure("rs_abc123", {}, "not_eligible")

    def test_custom_test_name_is_forwarded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["test_name"] == "my_scenario"
            return httpx.Response(200, json={"failing_criterion": "x"})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.explain_failure("rs_abc123", {}, "eligible", test_name="my_scenario")

    def test_expected_outcome_eligible(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "eligible"
            return httpx.Response(200, json={})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.explain_failure("rs_abc123", {}, "eligible")

    def test_expected_outcome_not_eligible(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "not_eligible"
            return httpx.Response(200, json={})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.explain_failure("rs_abc123", {}, "not_eligible")

    def test_expected_outcome_undetermined(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "undetermined"
            return httpx.Response(200, json={})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.explain_failure("rs_abc123", {}, "undetermined")

    def test_422_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "expected_outcome"], "msg": "value is not a valid enum member"}]},
            )

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.explain_failure("rs_abc123", {}, "invalid_outcome")
        assert exc_info.value.status_code == 422


class TestErrorDetail:
    """4xx responses attach the API's ``detail``/``body`` to the exception."""

    def test_detail_appears_in_message_and_attribute(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "Provide exactly one of ruleset_id or rulebook_id"})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("ruleset:v1", {})

        err = exc_info.value
        assert err.status_code == 422
        assert err.detail == "Provide exactly one of ruleset_id or rulebook_id"
        assert err.body == {"detail": "Provide exactly one of ruleset_id or rulebook_id"}
        assert "422" in str(err)
        assert "Provide exactly one of ruleset_id or rulebook_id" in str(err)

    def test_list_detail_is_preserved(self):
        """FastAPI validation errors return ``detail`` as a list of objects."""
        detail = [{"loc": ["body", "expected_outcome"], "msg": "value is not a valid enum member"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": detail})

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("ruleset:v1", {})

        assert exc_info.value.detail == detail

    def test_missing_detail_leaves_attributes_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="not json")

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("ruleset:v1", {})

        err = exc_info.value
        assert err.detail is None
        assert err.body is None
        assert str(err) == "Aethis API returned 400"


class TestIncludeExplanation:
    """``include_explanation`` is sent on the request and the dict-shaped
    explanation round-trips back onto ``DecideResponse``."""

    def test_include_explanation_sent_and_defaults_false(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=make_decide_response())

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            client.decide("ruleset:v1", {})
            client.decide("ruleset:v1", {}, include_explanation=True)
            client.decide_rulebook("aethis/uk-fsm", {}, include_explanation=True)

        assert seen[0]["include_explanation"] is False
        assert seen[1]["include_explanation"] is True
        assert seen[2]["include_explanation"] is True

    def test_explanation_object_round_trips(self):
        explanation = {
            "decision": "eligible",
            "groups": [
                {
                    "group": "age",
                    "status": "satisfied",
                    "criteria": [{"criterion_id": "c1", "title": "18 or over", "status": "satisfied"}],
                }
            ],
            "unused_facts": ["nickname"],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_decide_response(decision="eligible", explanation=explanation))

        with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = client.decide("ruleset:v1", {}, include_explanation=True)

        assert resp.explanation == explanation
        assert resp.explanation["groups"][0]["status"] == "satisfied"


class TestListRulesets:
    """``GET /api/v1/public/rulesets`` catalogue wrapper."""

    def test_happy_path_returns_summaries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets"
            assert request.method == "GET"
            assert request.url.params["limit"] == "20"
            assert request.url.params["offset"] == "0"
            return httpx.Response(
                200,
                json=[
                    make_ruleset_summary(),
                    make_ruleset_summary(
                        ruleset_id="legacy:20260101-deadbeef",
                        slug="aethis/legacy",
                        section_id="legacy",
                        name=None,
                    ),
                ],
            )

        with Aethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            rulesets = client.list_rulesets()

        assert len(rulesets) == 2
        assert isinstance(rulesets[0], RulesetSummary)
        assert rulesets[0].slug == "aethis/construction-all-risks"
        assert rulesets[1].name is None

    def test_limit_and_offset_forwarded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["limit"] == "5"
            assert request.url.params["offset"] == "10"
            return httpx.Response(200, json=[])

        with Aethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            assert client.list_rulesets(limit=5, offset=10) == []


class TestConfig:
    def test_https_enforced_on_non_local_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            Aethis(api_key="k", base_url="http://api.example.com")

    def test_raises_if_used_outside_context(self):
        client = Aethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        with pytest.raises(RuntimeError, match="not open"):
            client.decide("b:v1", {})
