from __future__ import annotations

from plotsrv import store


def test_view_menu_revision_changes_only_when_menu_metadata_changes() -> None:
    store.reset()
    before = store.get_view_menu_revision()

    view_id = store.register_view(section="demo", label="summary", kind="artifact")
    registered = store.get_view_menu_revision()

    assert registered > before

    store.register_view(
        view_id=view_id,
        section="demo",
        label="summary",
        kind="artifact",
    )
    assert store.get_view_menu_revision() == registered

    store.set_artifact(obj="first", kind="text", view_id=view_id)
    published = store.get_view_menu_revision()
    assert published > registered

    store.set_artifact(obj="second", kind="text", view_id=view_id)
    assert store.get_view_menu_revision() == published
