"""Async client tests — uses httpx.MockTransport to avoid real HTTP."""

from __future__ import annotations

import json

import httpx
import pytest

from aethis_sdk import (
    AethisAPIError,
    AethisUnavailable,
    AsyncAethis,
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
    async def test_returns_parsed_response_on_200(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            assert request.url.path == "/api/v1/public/decide"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["ruleset_id"] == "test_ruleset:v1"
            assert body["field_values"] == {"age": 25}
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        async with AsyncAethis(
            api_key="test-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            resp = await client.decide("test_ruleset:v1", {"age": 25})

        assert isinstance(resp, DecideResponse)
        assert resp.decision == "eligible"
        assert call_count == 1

    async def test_sends_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "my-secret-key"
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(
            api_key="my-secret-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.decide("ruleset:v1", {})

    async def test_no_api_key_omits_x_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "x-api-key" not in request.headers
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.decide("ruleset:v1", {})

    async def test_decide_works_without_api_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        async with AsyncAethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.decide("aethis/construction-all-risks", {})

        assert resp.decision == "eligible"

    async def test_sends_iam_bearer_when_configured(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer iam-token-xyz"
            assert request.headers["x-api-key"] == "k"
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(
            api_key="k",
            base_url="http://test",
            iam_token="iam-token-xyz",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.decide("ruleset:v1", {})

    async def test_sends_include_trace(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["include_trace"] is True
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.decide("ruleset:v1", {}, include_trace=True)

    async def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Ruleset not found"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError, match="404") as exc_info:
                await client.decide("nonexistent:v1", {})
        assert exc_info.value.status_code == 404

    async def test_401_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Invalid API key"})

        async with AsyncAethis(api_key="bad", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError, match="401"):
                await client.decide("ruleset:v1", {})

    async def test_retries_once_on_500_then_succeeds(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, json={"detail": "Internal error"})
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.decide("ruleset:v1", {})

        assert resp.decision == "eligible"
        assert call_count == 2

    async def test_raises_unavailable_after_retries_exhausted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "Internal error"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisUnavailable):
                await client.decide("ruleset:v1", {})


class TestDecideRulebook:
    """Aethis-ai/aethis-sdk-python#14 — async rulebook surface."""

    async def test_sends_rulebook_id_payload(self):
        import json

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

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.decide_rulebook("aethis/uk-fsm", {"child.age": 10})

        assert resp.decision == "eligible"
        assert resp.rulebook_id == "rb_kzZ_td0tbKW_OLRB"
        assert resp.ruleset_id is None


class TestGetSchema:
    async def test_returns_parsed_response_on_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/test_ruleset:v1/schema"
            assert request.method == "GET"
            return httpx.Response(200, json=make_schema_response())

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.get_schema("test_ruleset:v1")

        assert isinstance(resp, SchemaResponse)
        assert resp.ruleset_id == "test_ruleset:v1"
        assert len(resp.fields) == 3
        assert resp.fields[0].field_id == "age"
        assert resp.fields[0].field_type == "integer"

    async def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Not found"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError, match="404"):
                await client.get_schema("nonexistent:v1")


class TestGenerationRecovery:
    async def test_get_generation_status_is_a_single_observational_read(self):
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
                    "job": {"job_id": "job_123", "status": "running", "progress_percent": 50},
                },
            )

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            response = await client.get_generation_status("proj_123")

        assert isinstance(response, GenerationStatusResponse)
        assert response.job is not None
        assert calls == 1

    async def test_cancel_generation_is_an_explicit_cooperative_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/public/projects/proj_123/generate/cancel"
            return httpx.Response(
                200,
                json={
                    "job_id": "job_123",
                    "status": "failed",
                    "project_released": True,
                    "detail": "The worker observes cancellation at its next boundary.",
                },
            )

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            response = await client.cancel_generation("proj_123")

        assert isinstance(response, GenerationCancellationResponse)
        assert response.status == "failed"


class TestReadOnlyEndpoints:
    async def test_whoami(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/me"
            return httpx.Response(200, json={"tenant_id": "t1", "tier": "internal"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.whoami()
        assert resp == {"tenant_id": "t1", "tier": "internal"}

    async def test_explain(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/b:v1/explain"
            return httpx.Response(200, json={"sections": []})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.explain("b:v1")
        assert resp == {"sections": []}

    async def test_get_source(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/b:v1/source"
            return httpx.Response(200, json={"text": "legislation excerpt"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.get_source("b:v1")
        assert resp == {"text": "legislation excerpt"}


class TestExplainFailure:
    """POST /api/v1/public/rulesets/{ruleset_id}/explain-failure SDK wrapper — async."""

    async def test_happy_path_returns_dict(self):
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

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.explain_failure("rs_abc123", {"age": 15}, "eligible")

        assert resp == expected_response

    async def test_default_test_name_is_test(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["test_name"] == "test"
            return httpx.Response(200, json={"failing_criterion": "x"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.explain_failure("rs_abc123", {}, "not_eligible")

    async def test_custom_test_name_is_forwarded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["test_name"] == "my_scenario"
            return httpx.Response(200, json={"failing_criterion": "x"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.explain_failure("rs_abc123", {}, "eligible", test_name="my_scenario")

    async def test_expected_outcome_eligible(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "eligible"
            return httpx.Response(200, json={})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.explain_failure("rs_abc123", {}, "eligible")

    async def test_expected_outcome_not_eligible(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "not_eligible"
            return httpx.Response(200, json={})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.explain_failure("rs_abc123", {}, "not_eligible")

    async def test_expected_outcome_undetermined(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["expected_outcome"] == "undetermined"
            return httpx.Response(200, json={})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.explain_failure("rs_abc123", {}, "undetermined")

    async def test_422_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "expected_outcome"], "msg": "value is not a valid enum member"}]},
            )

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                await client.explain_failure("rs_abc123", {}, "invalid_outcome")
        assert exc_info.value.status_code == 422


class TestErrorDetail:
    """4xx responses attach the API's ``detail``/``body`` to the exception."""

    async def test_detail_appears_in_message_and_attribute(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "Provide exactly one of ruleset_id or rulebook_id"})

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                await client.decide("ruleset:v1", {})

        err = exc_info.value
        assert err.status_code == 422
        assert err.detail == "Provide exactly one of ruleset_id or rulebook_id"
        assert err.body == {"detail": "Provide exactly one of ruleset_id or rulebook_id"}
        assert "422" in str(err)
        assert "Provide exactly one of ruleset_id or rulebook_id" in str(err)


class TestIncludeExplanation:
    """``include_explanation`` is sent and a dict explanation round-trips back."""

    async def test_include_explanation_sent_and_defaults_false(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            await client.decide("ruleset:v1", {})
            await client.decide("ruleset:v1", {}, include_explanation=True)
            await client.decide_rulebook("aethis/uk-fsm", {}, include_explanation=True)

        assert seen[0]["include_explanation"] is False
        assert seen[1]["include_explanation"] is True
        assert seen[2]["include_explanation"] is True

    async def test_explanation_object_round_trips(self):
        explanation = {
            "decision": "eligible",
            "groups": [{"group": "age", "status": "satisfied", "criteria": []}],
            "unused_facts": ["nickname"],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=make_decide_response(decision="eligible", explanation=explanation))

        async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            resp = await client.decide("ruleset:v1", {}, include_explanation=True)

        assert resp.explanation == explanation


class TestListRulesets:
    """``GET /api/v1/public/rulesets`` catalogue wrapper."""

    async def test_happy_path_returns_summaries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets"
            assert request.method == "GET"
            return httpx.Response(200, json=[make_ruleset_summary()])

        async with AsyncAethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            rulesets = await client.list_rulesets()

        assert len(rulesets) == 1
        assert isinstance(rulesets[0], RulesetSummary)
        assert rulesets[0].slug == "aethis/construction-all-risks"

    async def test_limit_and_offset_forwarded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["limit"] == "5"
            assert request.url.params["offset"] == "10"
            return httpx.Response(200, json=[])

        async with AsyncAethis(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            assert await client.list_rulesets(limit=5, offset=10) == []


class TestConfig:
    def test_https_enforced_on_non_local_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            AsyncAethis(api_key="k", base_url="http://api.example.com")

    def test_http_allowed_for_localhost(self):
        client = AsyncAethis(api_key="k", base_url="http://localhost:8080")
        assert client._base_url == "http://localhost:8080"

    def test_http_allowed_with_mock_transport(self):
        client = AsyncAethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        assert client._base_url == "http://test"

    async def test_raises_if_used_outside_context(self):
        client = AsyncAethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        with pytest.raises(RuntimeError, match="not open"):
            await client.decide("b:v1", {})
