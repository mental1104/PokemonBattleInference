"""锁定真实WebP资源的注册媒体类型及旧导入器的未知类型回退。"""

from __future__ import annotations

import mimetypes

import pytest

from pokeop.persistence.assets import importer


class TestSpriteMIME:
    """纯MIME边界测试；不连接数据库，不把精简系统的类型表缺项当成合法图片类型。"""

    @pytest.mark.parametrize(
        "relative",
        ["pokemon/versions/generation-ix/champions/1000.webp", "pokemon/1000.WEBP"],
    )
    def test_webp_without_system_registration(
        self, relative: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """relative为两种扩展名大小写；monkeypatch模拟已实测的WebP类型表缺项并在退出恢复。"""

        def missing_type(_path: str) -> tuple[None, None]:
            """_path是被查询的资源名；返回缺少MIME/编码记录，不修改模块或文件。"""
            return None, None

        monkeypatch.setattr(mimetypes, "guess_type", missing_type)
        assert importer._mime_type(relative) == "image/webp"
        assert importer._mime_type("opaque.unknown-extension") == "application/octet-stream"

    @pytest.mark.parametrize(
        "relative,expected",
        [
            ("pokemon/212.png", "image/png"),
            ("pokemon/other/showdown/212.gif", "image/gif"),
            ("pokemon/other/dream-world/212.svg", "image/svg+xml"),
            ("opaque.unknown-extension", "application/octet-stream"),
        ],
    )
    def test_existing_media_and_unknown_fallback(
        self, relative: str, expected: str
    ) -> None:
        """relative/expected为既有格式和未知扩展名的完整预期，确保修复保持原回退语义。"""
        assert importer._mime_type(relative) == expected
