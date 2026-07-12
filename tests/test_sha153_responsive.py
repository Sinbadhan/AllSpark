"""SHA-153: Repository responsive layout must actually work.

The project has no Tailwind build, so md:-prefixed utility classes must be
defined locally in base.html. Without them, `hidden md:block` stays hidden on
desktop (file tree invisible) and `md:hidden` stays visible (toggle button on
desktop) - the Repository layout was broken.
"""
from pathlib import Path


def _read(name: str) -> str:
    return (Path("allspark/templates") / name).read_text(encoding="utf-8")


class TestResponsiveUtilities:
    def test_md_utilities_defined_in_css(self):
        t = _read("base.html")
        # SHA-153: every md:-prefixed class used in templates must have a CSS
        # rule in the >=768px media block (no Tailwind build).
        for cls in ("md\\:flex-row", "md\\:block", "md\\:hidden", "md\\:w-64",
                    "md\\:col-span-2", "md\\:grid-cols-2"):
            assert cls in t, f"missing responsive CSS for .{cls}"

    def test_md_utilities_inside_media_query(self):
        t = _read("base.html")
        # The md: rules must be inside the @media (min-width: 768px) block.
        media_start = t.find("@media (min-width: 768px)")
        media_end = t.find("@media (max-width: 767px)", media_start)
        assert media_start >= 0 and media_end > media_start
        block = t[media_start:media_end]
        assert "md\\:flex-row" in block
