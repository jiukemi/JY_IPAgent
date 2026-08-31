"""Share link normalization for multi-platform paste text."""

from script.share_link import normalize_share_input, parse_channels_link


def test_normalize_weixin_sph_video():
    url = normalize_share_input("复制打开微信，看看【某某】 https://weixin.qq.com/sph/AkBAEKjbtY 的视频")
    assert url == "https://weixin.qq.com/sph/AkBAEKjbtY"


def test_normalize_channels_weixin_domain():
    url = normalize_share_input(
        "https://channels.weixin.qq.com/platform/post/abc123?feedId=14980729932764744213"
    )
    assert "channels.weixin.qq.com" in url
    assert "feedId=14980729932764744213" in url


def test_normalize_finder_video_domain():
    url = normalize_share_input("https://finder.video.qq.com/web/player?objectId=123456789012345678")
    assert url.startswith("https://finder.video.qq.com/")


def test_parse_channels_link_sph():
    meta = parse_channels_link("https://weixin.qq.com/sph/AI7ZDceho?feedId=1234567890")
    assert meta["sph_id"] == "AI7ZDceho"
    assert meta["feed_id"] == "1234567890"


def test_parse_channels_link_bare_sph():
    meta = parse_channels_link("https://weixin.qq.com/sph/AkBAEKjbtY")
    assert meta["sph_id"] == "AkBAEKjbtY"
    assert meta["feed_id"] is None
