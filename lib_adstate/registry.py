"""Discovery of the ADetailer-Neo components we need to read and write.

ADetailer-Neo builds every widget with a deterministic ``elem_id``, so instead of
reverse-engineering ids we compute the ids we expect and match components against
that table as they are created.

The per-tab ``gr.State`` objects carry no ``elem_id`` at all, so those are taken
from ``script.controls``, which the script runner fills with exactly the list
returned by ``AfterDetailerScript.ui()``.
"""

from __future__ import annotations

from typing import Any

from . import IMG2IMG_TAB_PROFILES, TAB_NAMES

ADETAILER_TITLE = "adetailer"


class ADetailerMissing(RuntimeError):
    """ADetailer-Neo is not installed, or its layout is not one we understand."""


def _ordinal(n: int) -> str:
    d = {1: "st", 2: "nd", 3: "rd"}
    return str(n) + ("th" if 11 <= n % 100 <= 13 else d.get(n % 10, "th"))


def _suffix(n: int, c: str = " ") -> str:
    return "" if n == 0 else c + _ordinal(n + 1)


def elem_id(item_id: str, n: int | None, tabname: str) -> str:
    """Mirror of ``lib_adetailer.ui.elem_id``."""
    suf = "" if n is None else _suffix(n, "_")
    return f"script_{tabname}_adetailer_{item_id}{suf}"


def all_args() -> Any:
    try:
        from lib_adetailer.args import ALL_ARGS
    except Exception as exc:
        raise ADetailerMissing(f"cannot import lib_adetailer.args: {exc}") from exc
    return ALL_ARGS


def num_models() -> int:
    from modules.shared import opts

    return int(opts.data.get("ad_max_models", 2))


class Registry:
    """Components captured while the UI is being constructed."""

    def __init__(self) -> None:
        # (tabname, n, attr) -> gradio component
        self.widgets: dict[tuple[str, int, str], Any] = {}
        # elem_id -> (tabname, n, attr), precomputed lookup table
        self._expected: dict[str, tuple[str, int, str]] = {}
        # elem_id -> gr.TabItem for the six img2img sub-tabs
        self.img2img_tabs: dict[str, Any] = {}
        # Tab count the expectation table was built for; None means "not built".
        self._built_for: int | None = None

    def reset(self) -> None:
        """Forget everything captured during a previous UI build.

        Registered with ``on_before_ui``, so each "Reload UI" starts clean.
        Without this, components from the closed UI would linger and -- more
        importantly -- the expectation table would still be sized for the
        previous "Max Tabs" (``ad_max_models``) setting.
        """
        self.widgets.clear()
        self._expected.clear()
        self.img2img_tabs.clear()
        self._built_for = None

    def build_expectations(self) -> None:
        count = num_models()

        # "Max Tabs" is a user setting that can change between UI builds, so the
        # table is rebuilt whenever the count differs.
        if self._built_for == count:
            return

        args = all_args()

        # Widgets from the previous build are dead Gradio objects once the tab
        # count changes, so drop them along with the stale table.
        self.widgets.clear()
        self._expected.clear()
        for tabname in TAB_NAMES:
            for n in range(count):
                for attr in args.attrs:
                    self._expected[elem_id(attr, n, tabname)] = (tabname, n, attr)

        self._built_for = count

    def observe(self, component: Any) -> None:
        """Called for every component created anywhere in the UI."""
        eid = getattr(component, "elem_id", None)
        if not eid:
            return

        if eid in IMG2IMG_TAB_PROFILES:
            self.img2img_tabs[eid] = component
            return

        if not eid.startswith("script_"):
            return

        # Checked on every component rather than once, so a "Max Tabs" change
        # is picked up even if the reset hook never ran.
        try:
            self.build_expectations()
        except ADetailerMissing:
            return

        key = self._expected.get(eid)
        if key is not None:
            self.widgets[key] = component

    # region lookups

    def widget(self, tabname: str, n: int, attr: str) -> Any:
        return self.widgets.get((tabname, n, attr))

    def tab_widgets(self, tabname: str, n: int) -> dict[str, Any]:
        """All widgets of one ADetailer sub-tab, keyed by attribute name."""
        found = {}
        for attr in all_args().attrs:
            component = self.widget(tabname, n, attr)
            if component is not None:
                found[attr] = component
        return found

    def is_complete(self, tabname: str) -> bool:
        attrs = all_args().attrs
        return all(
            self.widget(tabname, n, attr) is not None
            for n in range(num_models())
            for attr in attrs
        )

    def missing(self, tabname: str) -> list[str]:
        return [
            elem_id(attr, n, tabname)
            for n in range(num_models())
            for attr in all_args().attrs
            if self.widget(tabname, n, attr) is None
        ]


registry = Registry()


def _is_adetailer(script: Any) -> bool:
    name = getattr(script, "name", None)
    if isinstance(name, str) and name.lower() == ADETAILER_TITLE:
        return True

    # ``script.name`` is only assigned after the script's UI is built; fall back
    # to the title so lookups also work earlier.
    try:
        title = script.title()
    except Exception:
        return False

    return isinstance(title, str) and title.lower() == ADETAILER_TITLE


def adetailer_controls(is_img2img: bool) -> tuple[Any, Any, list[Any]]:
    """Return ``(ad_enable, ad_skip_img2img, [state_per_tab, ...])``.

    These come straight from the components ADetailer returned from ``ui()``,
    which is the only way to reach the per-tab ``gr.State`` objects. Writing
    those states is what actually changes what ADetailer does at generation
    time -- the visible widgets alone have no effect.
    """
    from modules import scripts as _scripts

    runner = _scripts.scripts_img2img if is_img2img else _scripts.scripts_txt2img
    if runner is None:
        raise ADetailerMissing("script runner not initialised")

    for script in runner.alwayson_scripts:
        if not _is_adetailer(script):
            continue

        controls = getattr(script, "controls", None)
        if not controls or len(controls) < 3:
            raise ADetailerMissing(
                "ADetailer returned an unexpected control layout "
                f"({0 if not controls else len(controls)} controls)"
            )

        ad_enable, ad_skip = controls[0], controls[1]
        states = list(controls[2:])

        if len(states) != num_models():
            raise ADetailerMissing(
                f"expected {num_models()} ADetailer tabs, found {len(states)}"
            )

        return ad_enable, ad_skip, states

    raise ADetailerMissing("ADetailer-Neo script not found")
