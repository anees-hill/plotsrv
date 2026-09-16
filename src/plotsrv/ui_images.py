"""Small, prebuilt copies of package images used by the browser UI."""

_ICON_NAMES = (
    "logo_unknown",
    "logo_plot",
    "logo_table",
    "logo_stream",
    "logo_image",
    "logo_markdown",
    "logo_json",
    "logo_observe",
    "logo_python",
    "logo_python_traceback",
    "logo_exception",
    "logo_txt",
    "logo_html",
    "logo_on_disk",
)
# (source relative to static/, longest edge in pixels). Keep enough resolution
# for high-density displays without decoding megapixel images for tiny controls.
UI_IMAGE_SOURCES = {
    **{name + ".png": 128 for name in _ICON_NAMES},
    "icons/header-settings.png": 128,
    "plotsrv_icon_logo.png": 192,
    "plotsrv_icon_title_colour_swash_logo.png": 768,
    "plotsrv_title_logo_ui-white-bk.png": 768,
}
UI_IMAGE_URLS = {
    "/static/" + source: "/static/ui-images/" + source.rsplit("/", 1)[-1]
    for source in UI_IMAGE_SOURCES
}


def ui_image_url(url: str) -> str:
    """Map package UI artwork only; user-configured/custom URLs stay as supplied."""
    return UI_IMAGE_URLS.get(url, url)
