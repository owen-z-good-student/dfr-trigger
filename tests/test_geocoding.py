import pytest
import httpx
from fastapi.testclient import TestClient

from app.geocoding import Geocoder
from app.main import create_app
from app.settings import Settings


@pytest.mark.asyncio
async def test_geocoder_uses_fixed_nominatim_host(respx_mock):
    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=__import__("httpx").Response(
            200,
            json=[{"lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"}],
        )
    )
    result = await Geocoder(timeout_seconds=1).search("Paris")
    assert route.called
    assert result.latitude == 48.8566
    assert result.longitude == 2.3522


@pytest.mark.asyncio
async def test_geocoder_rejects_blank_query():
    with pytest.raises(ValueError, match="query is required"):
        await Geocoder(timeout_seconds=1).search("   ")


@pytest.mark.asyncio
async def test_geocoder_user_agent_header(respx_mock):
    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=__import__("httpx").Response(
            200,
            json=[{"lat": "51.5074", "lon": "-0.1278", "display_name": "London, UK"}],
        )
    )
    await Geocoder(timeout_seconds=1).search("London")
    request = route.calls[0].request
    assert request.headers.get("user-agent") == "DFR-Trigger/0.1"


@pytest.mark.asyncio
async def test_geocoder_returns_none_on_no_results(respx_mock):
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=__import__("httpx").Response(200, json=[])
    )
    result = await Geocoder(timeout_seconds=1).search("ZZZNonexistentPlace")
    assert result is None


@pytest.mark.asyncio
async def test_geocoder_caches_repeated_query(respx_mock):
    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=__import__("httpx").Response(
            200,
            json=[{"lat": "48.8566", "lon": "2.3522", "display_name": "Paris, France"}],
        )
    )
    geocoder = Geocoder(timeout_seconds=1)
    await geocoder.search("CachableCity")
    await geocoder.search("CachableCity")
    # Second call should be served from cache, HTTP only called once
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_geocoder_instances_do_not_share_cache_or_event_loop_lock(respx_mock):
    route = respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[{"lat": "1.0", "lon": "2.0", "display_name": "Synthetic"}],
        )
    )
    first = Geocoder(timeout_seconds=1, min_interval_seconds=0)
    second = Geocoder(timeout_seconds=1, min_interval_seconds=0)
    await first.search("Shared query")
    await second.search("Shared query")
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_geocoder_rejects_oversized_provider_response(respx_mock):
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[{"lat": "1", "lon": "2", "display_name": "x" * 70_000}],
        )
    )
    with pytest.raises(RuntimeError, match="response too large"):
        await Geocoder(timeout_seconds=1, min_interval_seconds=0).search("Large")


def _csrf_headers(client: TestClient) -> dict[str, str]:
    assert client.get("/api/bootstrap").status_code == 200
    token = client.cookies.get("dfr_csrf")
    return {
        "origin": "http://testserver",
        "referer": "http://testserver/geocode",
        "x-csrf-token": token,
    }


def test_geocode_endpoint_enforces_per_member_rate_limit(tmp_path):
    class StubGeocoder:
        async def search(self, query):
            return type(
                "Result",
                (),
                {"latitude": 1.0, "longitude": 2.0, "display_name": "Synthetic"},
            )()

    settings = Settings(data_dir=tmp_path, geocodes_per_user_per_minute=2, public_origin="http://testserver")
    with TestClient(create_app(settings)) as client:
        client.app.state.geocoder = StubGeocoder()
        headers = _csrf_headers(client)
        first = client.post("/api/geocode", headers=headers, json={"query": "A"})
        second = client.post("/api/geocode", headers=headers, json={"query": "B"})
        third = client.post("/api/geocode", headers=headers, json={"query": "C"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
