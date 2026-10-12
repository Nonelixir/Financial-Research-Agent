import asyncio

import httpx

from finagent.config import Settings
from finagent.data.sec import SecClient


def test_company_search_normalizes_cik() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.sec.gov"
        return httpx.Response(
            200,
            json={
                "0": {
                    "cik_str": 1158114,
                    "ticker": "AAOI",
                    "title": "Applied Optoelectronics Inc",
                }
            },
        )

    async def run() -> None:
        client = SecClient(
            Settings(sec_identity="Test test@example.com"),
            transport=httpx.MockTransport(handler),
        )
        companies = await client.search_companies("AAOI")
        await client.close()
        assert companies[0].cik == "0001158114"

    asyncio.run(run())


def test_sec_client_rejects_unknown_hosts() -> None:
    async def run() -> None:
        client = SecClient(Settings(sec_identity="Test test@example.com"))
        try:
            try:
                await client._get("https://example.com/file")
            except ValueError as exc:
                assert "SEC hosts" in str(exc)
        finally:
            await client.close()

    asyncio.run(run())
