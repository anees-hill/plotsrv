"""Plot image sizing against the rendered page and dock in Chromium."""

import pytest

from tests.test_expanded_view_browser import expand, mount
from tests.test_plot_controls_browser import page


def geometry(page):
    return page.evaluate("""() => {
      const image = document.querySelector('#plot');
      const frame = image.closest('.plot-frame--plot');
      const dock = document.querySelector('.ps-bottom-dock');
      const rect = image.getBoundingClientRect();
      return {width: rect.width, height: rect.height,
        frameWidth: frame.clientWidth, frameHeight: frame.clientHeight,
        viewportHeight: innerHeight,
        dockTop: dock.hidden ? innerHeight : dock.getBoundingClientRect().top,
        imageBottom: rect.bottom,
        naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight};
    }""")


@pytest.mark.parametrize("size", [(640, 480), (500, 1800), (1800, 400)])
def test_initial_plot_fits_available_viewport_and_preserves_aspect(page, size):
    mount(page, "plots:figure", plot_size=size)
    page.wait_for_function("!document.querySelector('#plot-size-controls').hidden")
    fitted = geometry(page)
    assert fitted["width"] <= fitted["frameWidth"]
    assert fitted["imageBottom"] <= fitted["dockTop"] - 8
    assert fitted["height"] / fitted["width"] == pytest.approx(size[1] / size[0], rel=0.005)
    assert fitted["width"] <= size[0]


def test_plot_controls_and_layout_changes_resize_only_the_plot(page):
    mount(page, "plots:figure", plot_size=(500, 1800))
    page.wait_for_function("!document.querySelector('#plot-size-controls').hidden")
    initial = geometry(page)
    page.get_by_role("button", name="Increase plot size").click()
    larger = geometry(page)
    assert larger["width"] > initial["width"]
    assert larger["height"] > initial["height"]
    assert larger["frameHeight"] <= initial["frameHeight"] + 3
    page.get_by_role("button", name="Decrease plot size").click()
    assert geometry(page)["width"] == pytest.approx(initial["width"], abs=1)
    page.get_by_role("button", name="Increase plot size").click()
    page.get_by_role("button", name="Fit", exact=True).click()
    assert geometry(page)["width"] == pytest.approx(initial["width"], abs=1)

    page.set_viewport_size({"width": 800, "height": 600})
    page.wait_for_function("document.querySelector('#plot').getBoundingClientRect().height < 400")
    smaller = geometry(page)
    assert smaller["imageBottom"] <= smaller["dockTop"] - 8
    expand(page)
    page.wait_for_function("document.querySelector('#plot').getBoundingClientRect().height > 400")
    expanded = geometry(page)
    assert expanded["imageBottom"] <= expanded["viewportHeight"]
