import unittest

from app.baidu.client import BaiduAPIError
from app.baidu.services.adgroup import AdgroupService
from app.baidu.services.campaign import CampaignService
from app.baidu.services.keyword import KeywordService


class FakeClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def call(self, service, method, body, **kwargs):
        self.calls.append((service, method, body, kwargs))
        result = self.handler(service, method, body)
        if isinstance(result, Exception):
            raise result
        return result


class AdgroupFetchIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_campaign_is_isolated_without_losing_valid_results(self):
        def handler(_service, _method, body):
            ids = body["ids"]
            if 22 in ids:
                return BaiduAPIError(91001, "Campaign id not exist")
            return {"data": [{"campaignId": value} for value in ids]}

        client = FakeClient(handler)
        result = await AdgroupService(client).get_adgroups_by_campaign_ids([11, 22, 33])

        self.assertEqual(result, [{"campaignId": 11}, {"campaignId": 33}])
        self.assertTrue(
            all("priceRatio" in call[2]["adgroupFields"] for call in client.calls)
        )

    async def test_unrelated_error_is_not_misclassified_as_probe_field_failure(self):
        error = BaiduAPIError(89501, "You are not authorized to access this method")
        client = FakeClient(lambda *_args: error)

        with self.assertRaises(BaiduAPIError) as raised:
            await AdgroupService(client).get_adgroups_by_campaign_ids([11])

        self.assertIs(raised.exception, error)
        self.assertEqual(len(client.calls), 1)

    async def test_invalid_probe_field_is_removed_once_and_reused(self):
        def handler(_service, _method, body):
            if "priceRatio" in body["adgroupFields"]:
                return BaiduAPIError(9011519, "Request field is invalid")
            return {"data": [{"campaignId": value} for value in body["ids"]]}

        client = FakeClient(handler)
        campaign_ids = list(range(1, 102))
        result = await AdgroupService(client).get_adgroups_by_campaign_ids(campaign_ids)

        self.assertEqual(len(result), 101)
        self.assertEqual(len(client.calls), 3)
        self.assertIn("priceRatio", client.calls[0][2]["adgroupFields"])
        self.assertNotIn("priceRatio", client.calls[1][2]["adgroupFields"])
        self.assertNotIn("priceRatio", client.calls[2][2]["adgroupFields"])


class KeywordFetchIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_keyword_id_is_removed_and_valid_keyword_is_returned(self):
        def handler(_service, _method, body):
            if 202002 in body["ids"]:
                return BaiduAPIError(
                    90180000259,
                    "winfoid 202002 not exists",
                    raw={
                        "header": {
                            "failures": [{"message": "winfoid 202002 not exists"}]
                        }
                    },
                )
            return {"data": [{"keywordId": value} for value in body["ids"]]}

        client = FakeClient(handler)
        result = await KeywordService(client).get_words_by_ids([101001, 202002])

        self.assertEqual(result, [{"keywordId": 101001}])

    async def test_missing_adgroup_is_isolated_without_losing_valid_results(self):
        def handler(_service, _method, body):
            ids = body["ids"]
            if 202 in ids:
                return BaiduAPIError(92001, "Adgroup id not exist")
            return {"data": [{"adgroupId": value} for value in ids]}

        client = FakeClient(handler)
        result = await KeywordService(client).get_words_by_adgroup_ids([101, 202, 303])

        self.assertEqual(result, [{"adgroupId": 101}, {"adgroupId": 303}])

    async def test_unrelated_error_is_not_swallowed(self):
        error = BaiduAPIError(500, "upstream unavailable")
        client = FakeClient(lambda *_args: error)

        with self.assertRaises(BaiduAPIError) as raised:
            await KeywordService(client).get_words_by_adgroup_ids([101, 202])

        self.assertIs(raised.exception, error)
        self.assertEqual(len(client.calls), 1)

    async def test_unrelated_error_containing_asset_id_is_not_swallowed(self):
        error = BaiduAPIError(
            89501,
            "request 101001 is not authorized",
            raw={"header": {"failures": [{"message": "request 101001 is not authorized"}]}},
        )
        client = FakeClient(lambda *_args: error)

        with self.assertRaises(BaiduAPIError) as raised:
            await KeywordService(client).get_words_by_adgroup_ids([101001])

        self.assertIs(raised.exception, error)
        self.assertEqual(len(client.calls), 1)


class CampaignProbeFieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_error_is_not_retried_without_probe_field(self):
        error = BaiduAPIError(89501, "permission denied")
        client = FakeClient(lambda *_args: error)

        with self.assertRaises(BaiduAPIError) as raised:
            await CampaignService(client).get_all_campaigns()

        self.assertIs(raised.exception, error)
        self.assertEqual(len(client.calls), 1)

    async def test_known_invalid_field_error_retries_without_probe_field(self):
        def handler(_service, _method, body):
            if "priceRatio" in body["campaignFields"]:
                return BaiduAPIError(9011519, "Request field is invalid")
            return {"data": [{"campaignId": 1}]}

        client = FakeClient(handler)
        result = await CampaignService(client).get_all_campaigns()

        self.assertEqual(result, [{"campaignId": 1}])
        self.assertEqual(len(client.calls), 2)


if __name__ == "__main__":
    unittest.main()
