import pytest

from backend.channels.opencli_output import parse_opencli_json
from backend.services.douyin_import_service import _aweme_id_from_url, extract_douyin_url


def test_extract_douyin_url_from_full_share_text():
    text = "9.76 03/26 复制此链接 https://v.douyin.com/2Eiu7qmLsA8/ 打开抖音"
    assert extract_douyin_url(text) == "https://v.douyin.com/2Eiu7qmLsA8/"


def test_extract_aweme_id_from_canonical_url():
    assert _aweme_id_from_url(
        "https://www.douyin.com/video/7667379238509042118?previous_page=web_code_link"
    ) == "7667379238509042118"


def test_opencli_json_parser_ignores_update_notice_suffix():
    assert parse_opencli_json('{"status_code":0,"item":{"id":"1"}}\nUpdate available') == [
        {"status_code": 0, "item": {"id": "1"}}
    ]


def test_extract_douyin_url_rejects_other_sites():
    with pytest.raises(ValueError, match="抖音链接"):
        extract_douyin_url("https://example.com/video/1")
