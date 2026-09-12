import unittest
from unittest.mock import patch

import app


SAMPLE_PAYLOAD = {
    "isSuccess": True,
    "recommendList": [
        {
            "series_id": "123456789",
            "series_name": "穿越测试短剧",
            "episode_cnt": 80,
            "episode_right_text": "全80集",
            "series_cover": "https://example.com/cover.jpg",
            "series_intro": "一部用于验证搜索适配器的短剧。",
            "tags": ["穿越", "逆袭"],
            "celebrities": [{"nickname": "测试演员"}],
            "vid_list": ["episode-001", "episode-002", "episode-003"],
        }
    ],
}

SUGGESTION_PAYLOAD = {
    "suggest_list": [
        {
            "name": "霸总搜索结果",
            "keyword": "987654321",
            "word_type": "short_play_name",
            "video_data": {
                "series_id": 987654321,
                "series_title": "霸总搜索结果",
                "episode_cnt": 2,
                "episode_right_text": "全2集",
                "series_cover": "https://example.com/search.jpg",
                "series_intro": "来自关键词搜索。",
                "category_list": [{"name": "都市"}],
                "vid_list": ["search-episode-1", "search-episode-2"],
            },
        },
        {"name": "无关联想词", "keyword": "common-key", "word_type": "common_query", "video_data": {}},
    ]
}


class HongguoSearchTests(unittest.TestCase):
    def test_keyword_category_is_sent_to_current_api(self):
        params = app.build_hongguo_api_params("穿越", 2, "")

        self.assertEqual(params["categories_v2"], "cate_37")
        self.assertEqual(params["page_num"], 2)
        self.assertEqual(params["sort_type"], "1")

    def test_current_api_payload_is_normalized(self):
        items = app.parse_hongguo_api_items(SAMPLE_PAYLOAD)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "穿越测试短剧")
        self.assertEqual(items[0]["drama_id"], "123456789")
        self.assertEqual(items[0]["episodes"], "全80集")
        self.assertTrue(items[0]["downloadable"])
        self.assertEqual(items[0]["episode_ids"], ["episode-001", "episode-002", "episode-003"])
        self.assertIn("series_id=123456789", items[0]["source_url"])

    @patch("app.fetch_text")
    def test_detail_page_supplies_complete_episode_list(self, fetch_text):
        detail = {
            "loaderData": {
                "detail_page": {
                    "seriesDetail": {
                        "series_id": "987654321",
                        "series_name": "完整分集测试",
                        "episode_cnt": 4,
                        "episode_right_text": "全4集",
                        "vid_list": ["full-1", "full-2", "full-3", "full-4"],
                    }
                }
            }
        }
        fetch_text.return_value = f"<script>_ROUTER_DATA = {app.json.dumps(detail)}</script>"
        app.fetch_hongguo_series_item.cache_clear()

        item = app.fetch_hongguo_series_item("987654321")

        self.assertEqual(item["episodes"], "全4集")
        self.assertEqual(item["episode_ids"], ["full-1", "full-2", "full-3", "full-4"])

    @patch("app.fetch_json", return_value=SAMPLE_PAYLOAD)
    def test_search_uses_current_api(self, fetch_json):
        items = app.search_hongguo("", 1, "")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "穿越测试短剧")
        fetch_json.assert_called_once()

    @patch("app.fetch_json", return_value=SUGGESTION_PAYLOAD)
    def test_keyword_search_uses_suggestion_results_not_recommendations(self, fetch_json):
        items = app.search_hongguo("霸总", 1, "")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "霸总搜索结果")
        self.assertEqual(items[0]["episodes"], "全2集")
        self.assertEqual(items[0]["episode_ids"], ["search-episode-1", "search-episode-2"])
        self.assertIn("/incent_resource/suggestion", fetch_json.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
