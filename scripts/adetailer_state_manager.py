"""ADetailer State Manager.

Adds preset save/load on top of ADetailer-Neo, plus an optional split so the
img2img and Inpaint sub-tabs each keep their own ADetailer configuration.

ADetailer-Neo itself is never modified, so it stays updatable.
"""

from __future__ import annotations

import traceback
from typing import Any

import gradio as gr
from gradio.context import Context

import modules.scripts as scripts
from modules import script_callbacks
from modules.ui_components import FormRow

from lib_adstate import EXT_NAME, PROFILE_IMG2IMG, PROFILE_INPAINT, __version__
from lib_adstate import bridge, profiles, store
from lib_adstate.registry import (
    ADetailerMissing,
    adetailer_controls,
    all_args,
    num_models,
    registry,
)


def _log(message: str) -> None:
    print(f"[{EXT_NAME}] {message}")


def _on_after_component(component, **_kwargs):
    try:
        registry.observe(component)
    except Exception:
        pass


def _on_before_ui() -> None:
    # Every UI build (including "Reload UI") starts from a clean registry, so
    # stale components and a changed "Max Tabs" setting cannot leak across.
    try:
        registry.reset()
    except Exception:
        pass


script_callbacks.on_before_ui(_on_before_ui)
script_callbacks.on_after_component(_on_after_component)


def _ordinal(n: int) -> str:
    d = {1: "st", 2: "nd", 3: "rd"}
    return str(n) + ("th" if 11 <= n % 100 <= 13 else d.get(n % 10, "th"))


def _tab_choices(count: int) -> list[str]:
    return [f"{_ordinal(n + 1)} tab" for n in range(count)]


def _clamp_index(value: Any, count: int) -> int:
    """Keep a dropdown index inside the live tab range.

    Guards against a browser that is still showing choices from before the
    "Max Tabs" setting changed.
    """
    try:
        index = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(index, count - 1))


def _split_values(values: tuple[Any, ...], count: int) -> list[dict[str, Any]]:
    """Regroup the flat widget-value tuple into one dict per ADetailer tab."""
    attrs = all_args().attrs
    width = len(attrs)
    return [
        dict(zip(attrs, values[n * width : (n + 1) * width])) for n in range(count)
    ]


def _report(notes: list[str], context: str) -> None:
    if not notes:
        return

    head = notes[:4]
    if len(notes) > len(head):
        head.append(f"... and {len(notes) - len(head)} more")

    message = f"{context}: " + "; ".join(head)
    _log(message)
    gr.Warning(message)


class ADetailerStateManager(scripts.Script):
    # Render after ADetailer-Neo (which uses the default priority of 0) so its
    # controls already exist when our UI is built.
    sorting_priority = 100

    def title(self) -> str:
        return EXT_NAME

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        try:
            self._build(is_img2img)
        except ADetailerMissing as exc:
            _log(f"disabled - {exc}")
        except Exception:
            _log("disabled - unexpected error while building UI")
            traceback.print_exc()

        return []

    # region UI

    def _build(self, is_img2img: bool) -> None:
        tabname = "img2img" if is_img2img else "txt2img"
        count = num_models()
        attrs = all_args().attrs

        ad_enable, ad_skip, ad_states = adetailer_controls(is_img2img)

        registry.build_expectations()
        if not registry.is_complete(tabname):
            missing = registry.missing(tabname)
            raise ADetailerMissing(
                f"{len(missing)} {tabname} widgets not found (e.g. {missing[0]})"
            )

        widgets = [
            registry.widget(tabname, n, attr) for n in range(count) for attr in attrs
        ]
        tab_choices = _tab_choices(count)

        with gr.Accordion(
            "ADetailer Presets & Profiles",
            open=False,
            elem_id=f"adstate_{tabname}_accordion",
        ):
            gr.Markdown(
                "Presets are shared between txt2img and img2img. "
                "Loading applies values once - the ADetailer toggle and every "
                "setting keep working normally afterwards, and editing them "
                "never changes a saved preset."
            )

            with gr.Tab("Tab preset"):
                tab_ui = self._tab_preset_ui(tabname, tab_choices)

            with gr.Tab("Full preset"):
                full_ui = self._full_preset_ui(tabname)

            split_ui = None
            if is_img2img:
                with gr.Tab("img2img / Inpaint split"):
                    split_ui = self._split_ui(tabname)

            gr.Markdown(f"<sub>{EXT_NAME} v{__version__}</sub>")

        self._wire_tab_presets(tab_ui, tabname, count, widgets, ad_states)
        self._wire_full_presets(
            full_ui, tabname, count, widgets, ad_states, ad_enable, ad_skip
        )

        if split_ui is not None:
            self._wire_split(
                split_ui, tabname, count, widgets, ad_states, ad_enable, ad_skip
            )

        self._attach_page_load_refresh(tab_ui["preset"], full_ui["preset"])

    def _attach_page_load_refresh(self, tab_preset, full_preset) -> None:
        """Re-read the preset folder every time the page is (re)loaded.

        A Dropdown's choices are baked in when the UI is built, so presets saved
        afterwards disappear from the list as soon as the browser is refreshed -
        the files are still on disk, but the browser is handed the original,
        empty list. Refreshing on page load keeps the dropdowns truthful without
        needing a restart or a click on Refresh.
        """
        demo = Context.root_block
        if demo is None:
            _log(
                "could not hook page load; saved presets may need the Refresh "
                "button after a browser reload"
            )
            return

        def _refresh_on_load():
            return (
                gr.update(choices=store.list_presets("tab")),
                gr.update(choices=store.list_presets("full")),
            )

        demo.load(
            fn=_refresh_on_load,
            inputs=[],
            outputs=[tab_preset, full_preset],
            queue=False,
        )

    def _tab_preset_ui(self, tabname: str, tab_choices: list[str]) -> dict[str, Any]:
        eid = lambda name: f"adstate_{tabname}_tab_{name}"  # noqa: E731
        presets = store.list_presets("tab")

        with FormRow():
            name = gr.Textbox(
                label="Preset name",
                placeholder="e.g. face - strong",
                lines=1,
                max_lines=1,
                elem_id=eid("name"),
            )
            source = gr.Dropdown(
                label="Save from",
                choices=tab_choices,
                value=tab_choices[0],
                type="index",
                elem_id=eid("source"),
            )
            save = gr.Button("Save tab", variant="primary", elem_id=eid("save"))

        with FormRow():
            preset = gr.Dropdown(
                label="Saved tab presets",
                choices=presets,
                value=None,
                elem_id=eid("preset"),
            )
            target = gr.Dropdown(
                label="Load into",
                choices=tab_choices,
                value=tab_choices[0],
                type="index",
                elem_id=eid("target"),
            )
            load = gr.Button("Load tab", variant="primary", elem_id=eid("load"))

        with FormRow():
            refresh = gr.Button("Refresh", elem_id=eid("refresh"))
            delete = gr.Button("Delete", elem_id=eid("delete"))

        return {
            "name": name,
            "source": source,
            "save": save,
            "preset": preset,
            "target": target,
            "load": load,
            "refresh": refresh,
            "delete": delete,
        }

    def _full_preset_ui(self, tabname: str) -> dict[str, Any]:
        eid = lambda name: f"adstate_{tabname}_full_{name}"  # noqa: E731
        presets = store.list_presets("full")

        gr.Markdown(
            "Full presets cover every ADetailer tab plus the main ADetailer "
            "toggle and *Skip img2img*."
        )

        with FormRow():
            name = gr.Textbox(
                label="Preset name",
                placeholder="e.g. portrait setup",
                lines=1,
                max_lines=1,
                elem_id=eid("name"),
            )
            save = gr.Button("Save full setup", variant="primary", elem_id=eid("save"))

        with FormRow():
            preset = gr.Dropdown(
                label="Saved full presets",
                choices=presets,
                value=None,
                elem_id=eid("preset"),
            )
            load = gr.Button("Load full setup", variant="primary", elem_id=eid("load"))

        with FormRow():
            refresh = gr.Button("Refresh", elem_id=eid("refresh"))
            delete = gr.Button("Delete", elem_id=eid("delete"))

        return {
            "name": name,
            "save": save,
            "preset": preset,
            "load": load,
            "refresh": refresh,
            "delete": delete,
        }

    def _split_ui(self, tabname: str) -> dict[str, Any]:
        eid = lambda name: f"adstate_{tabname}_split_{name}"  # noqa: E731

        gr.Markdown(
            "Keep one ADetailer configuration for **img2img / Sketch / Batch** "
            "and another for **Inpaint / Inpaint sketch / Inpaint upload**. "
            "Switching sub-tabs swaps them. This lasts for the session only."
        )

        enabled = gr.Checkbox(
            value=True,
            label="Separate ADetailer config for img2img and Inpaint",
            elem_id=eid("enabled"),
        )
        session = gr.State(profiles.new_session)
        status = gr.Markdown(f"Active profile: **{profiles.label(PROFILE_IMG2IMG)}**")

        with FormRow():
            copy = gr.Button("Copy active profile to the other", elem_id=eid("copy"))
            reset = gr.Button("Reset both profiles", elem_id=eid("reset"))

        return {
            "enabled": enabled,
            "session": session,
            "status": status,
            "copy": copy,
            "reset": reset,
        }

    # region wiring

    def _wire_tab_presets(
        self,
        ui: dict[str, Any],
        tabname: str,
        count: int,
        widgets: list[Any],
        ad_states: list[Any],
    ) -> None:
        def do_save(preset_name, source_index, *values):
            try:
                per_tab = _split_values(values, count)
                index = _clamp_index(source_index, count)
                payload = {"tab": bridge.snapshot_from_values(per_tab[index])}

                overwrote = store.exists("tab", preset_name)
                path = store.save_preset("tab", preset_name, payload)
            except store.PresetError as exc:
                gr.Warning(str(exc))
                return gr.skip(), gr.skip()
            except Exception as exc:
                _log(f"save tab preset failed: {exc}")
                traceback.print_exc()
                gr.Warning(f"Could not save preset: {exc}")
                return gr.skip(), gr.skip()

            gr.Info(
                f'{"Overwrote" if overwrote else "Saved"} tab preset "{path.stem}"'
            )
            return (
                gr.update(choices=store.list_presets("tab"), value=path.stem),
                gr.update(value=""),
            )

        ui["save"].click(
            fn=do_save,
            inputs=[ui["name"], ui["source"], *widgets],
            outputs=[ui["preset"], ui["name"]],
            queue=False,
            show_progress=False,
        )

        def do_load(preset_name, target_index, *values):
            skip_all = [gr.skip()] * (len(widgets) + len(ad_states))

            if not preset_name:
                gr.Warning("Select a tab preset first")
                return skip_all

            try:
                document = store.load_preset("tab", preset_name)
            except store.PresetError as exc:
                gr.Warning(str(exc))
                return skip_all

            index = _clamp_index(target_index, count)
            per_tab = _split_values(values, count)
            tab_widgets = registry.tab_widgets(tabname, index)

            raw = document.get("tab")
            if not isinstance(raw, dict):
                gr.Warning(f'Preset "{preset_name}" contains no tab data')
                return skip_all

            clean, notes = bridge.sanitize(raw, tab_widgets, fallback=per_tab[index])
            _report(notes, f'Loading "{preset_name}"')

            updates = bridge.widget_updates(clean, tab_widgets)
            attrs = all_args().attrs

            result: list[Any] = []
            for n in range(count):
                for attr in attrs:
                    result.append(updates[attr] if n == index else gr.skip())

            # Writing the gr.State is what actually takes effect at generation
            # time; the widget updates above only keep the UI honest.
            for n in range(count):
                result.append(bridge.state_dict(clean) if n == index else gr.skip())

            gr.Info(f'Loaded "{preset_name}" into the {_ordinal(index + 1)} tab')
            return result

        ui["load"].click(
            fn=do_load,
            inputs=[ui["preset"], ui["target"], *widgets],
            outputs=[*widgets, *ad_states],
            queue=False,
            show_progress=False,
        )

        self._wire_list_buttons(ui, "tab")

    def _wire_full_presets(
        self,
        ui: dict[str, Any],
        tabname: str,
        count: int,
        widgets: list[Any],
        ad_states: list[Any],
        ad_enable: Any,
        ad_skip: Any,
    ) -> None:
        def do_save(preset_name, enable, skip, *values):
            try:
                per_tab = _split_values(values, count)
                payload = {
                    "enable": bool(enable),
                    "skip_img2img": bool(skip),
                    "tabs": [bridge.snapshot_from_values(v) for v in per_tab],
                }

                overwrote = store.exists("full", preset_name)
                path = store.save_preset("full", preset_name, payload)
            except store.PresetError as exc:
                gr.Warning(str(exc))
                return gr.skip(), gr.skip()
            except Exception as exc:
                _log(f"save full preset failed: {exc}")
                traceback.print_exc()
                gr.Warning(f"Could not save preset: {exc}")
                return gr.skip(), gr.skip()

            gr.Info(
                f'{"Overwrote" if overwrote else "Saved"} full preset "{path.stem}"'
            )
            return (
                gr.update(choices=store.list_presets("full"), value=path.stem),
                gr.update(value=""),
            )

        ui["save"].click(
            fn=do_save,
            inputs=[ui["name"], ad_enable, ad_skip, *widgets],
            outputs=[ui["preset"], ui["name"]],
            queue=False,
            show_progress=False,
        )

        def do_load(preset_name, *values):
            skip_all = [gr.skip()] * (2 + len(widgets) + len(ad_states))

            if not preset_name:
                gr.Warning("Select a full preset first")
                return skip_all

            try:
                document = store.load_preset("full", preset_name)
            except store.PresetError as exc:
                gr.Warning(str(exc))
                return skip_all

            stored_tabs = document.get("tabs")
            if not isinstance(stored_tabs, list) or not stored_tabs:
                gr.Warning(f'Preset "{preset_name}" contains no tab data')
                return skip_all

            per_tab = _split_values(values, count)
            config = self._config_from_document(
                document, stored_tabs, per_tab, tabname, count, preset_name
            )

            return self._apply_config(config, tabname, count)

        ui["load"].click(
            fn=do_load,
            inputs=[ui["preset"], *widgets],
            outputs=[ad_enable, ad_skip, *widgets, *ad_states],
            queue=False,
            show_progress=False,
        )

        self._wire_list_buttons(ui, "full")

    def _wire_list_buttons(self, ui: dict[str, Any], kind: str) -> None:
        def do_refresh(current):
            presets = store.list_presets(kind)
            value = current if current in presets else None
            return gr.update(choices=presets, value=value)

        ui["refresh"].click(
            fn=do_refresh,
            inputs=[ui["preset"]],
            outputs=[ui["preset"]],
            queue=False,
            show_progress=False,
        )

        def do_delete(preset_name):
            if not preset_name:
                gr.Warning("Select a preset first")
                return gr.skip()

            try:
                store.delete_preset(kind, preset_name)
            except store.PresetError as exc:
                gr.Warning(str(exc))
                return gr.skip()

            gr.Info(f'Deleted "{preset_name}"')
            return gr.update(choices=store.list_presets(kind), value=None)

        ui["delete"].click(
            fn=do_delete,
            inputs=[ui["preset"]],
            outputs=[ui["preset"]],
            queue=False,
            show_progress=False,
        )

    # region shared helpers

    def _config_from_document(
        self,
        document: dict[str, Any],
        stored_tabs: list[Any],
        per_tab: list[dict[str, Any]],
        tabname: str,
        count: int,
        context: str,
    ) -> dict[str, Any]:
        """Sanitize a stored full setup against this installation."""
        tabs: list[dict[str, Any]] = []
        notes: list[str] = []

        # "Max Tabs" can differ between the machine that saved the preset and
        # this one. Extra tabs are ignored; missing ones keep their current
        # values. Either way the user is told.
        if len(stored_tabs) > count:
            notes.append(
                f"preset has {len(stored_tabs)} tabs but only {count} are shown; "
                "the extra ones were ignored"
            )

        for n in range(count):
            fallback = per_tab[n]
            raw = stored_tabs[n] if n < len(stored_tabs) else None

            if not isinstance(raw, dict):
                tabs.append(dict(fallback))
                if n >= len(stored_tabs):
                    notes.append(f"preset has no {_ordinal(n + 1)} tab; left unchanged")
                continue

            clean, tab_notes = bridge.sanitize(
                raw, registry.tab_widgets(tabname, n), fallback=fallback
            )
            tabs.append(clean)
            notes.extend(f"{_ordinal(n + 1)} tab: {note}" for note in tab_notes)

        _report(notes, f'Loading "{context}"')

        return {
            "enable": bool(document.get("enable", False)),
            "skip_img2img": bool(document.get("skip_img2img", False)),
            "tabs": tabs,
        }

    def _current_config(
        self, enable: Any, skip: Any, values: tuple[Any, ...], count: int
    ) -> dict[str, Any]:
        return {
            "enable": bool(enable),
            "skip_img2img": bool(skip),
            "tabs": _split_values(values, count),
        }

    def _apply_config(
        self, config: dict[str, Any], tabname: str, count: int
    ) -> list[Any]:
        """Build ``[enable, skip, *widget updates, *state dicts]``."""
        attrs = all_args().attrs
        result: list[Any] = [
            gr.update(value=config["enable"]),
            gr.update(value=config["skip_img2img"]),
        ]

        per_tab_updates = []
        for n in range(count):
            values = config["tabs"][n]
            per_tab_updates.append(
                bridge.widget_updates(values, registry.tab_widgets(tabname, n))
            )

        for n in range(count):
            for attr in attrs:
                result.append(per_tab_updates[n].get(attr, gr.skip()))

        for n in range(count):
            result.append(bridge.state_dict(config["tabs"][n]))

        return result

    # region split

    def _wire_split(
        self,
        ui: dict[str, Any],
        tabname: str,
        count: int,
        widgets: list[Any],
        ad_states: list[Any],
        ad_enable: Any,
        ad_skip: Any,
    ) -> None:
        tabs = registry.img2img_tabs
        if not tabs:
            _log("img2img sub-tabs were not found; the split control is inactive")
            return

        session = ui["session"]
        enabled = ui["enabled"]
        status = ui["status"]

        swap_inputs = [session, enabled, ad_enable, ad_skip, *widgets]
        swap_outputs = [session, status, ad_enable, ad_skip, *widgets, *ad_states]
        untouched = [gr.skip()] * (2 + len(widgets) + len(ad_states))

        def make_swap(target_profile: str):
            def swap(state, split_on, enable, skip, *values):
                current = self._current_config(enable, skip, values, count)

                if not split_on:
                    return [gr.skip(), gr.skip(), *untouched]

                first_visit = profiles.normalize(state)["configs"].get(
                    target_profile
                ) is None

                state, incoming = profiles.switch(state, target_profile, current)
                label = profiles.label(target_profile)
                status_update = gr.update(value=f"Active profile: **{label}**")

                if first_visit and target_profile == PROFILE_INPAINT and skip:
                    gr.Info(
                        '"Skip img2img" was turned off for the Inpaint profile - '
                        "ADetailer does not run at all on Inpaint while it is on."
                    )

                if incoming is None:
                    return [state, status_update, *untouched]

                return [
                    state,
                    status_update,
                    *self._apply_config(incoming, tabname, count),
                ]

            return swap

        for elem_id, component in tabs.items():
            target = profiles.profile_for_tab(elem_id)
            if target is None:
                continue

            component.select(
                fn=make_swap(target),
                inputs=swap_inputs,
                outputs=swap_outputs,
                queue=False,
                show_progress=False,
            )

        def do_copy(state, split_on, enable, skip, *values):
            if not split_on:
                gr.Warning("Enable the split first")
                return gr.skip(), gr.skip()

            state = profiles.normalize(state)
            current = self._current_config(enable, skip, values, count)
            active = state["active"]
            destination = profiles.other(active)

            state["configs"][active] = current
            state["configs"][destination] = current

            gr.Info(
                f"Copied the {profiles.label(active)} profile "
                f"to {profiles.label(destination)}"
            )
            return state, gr.update(value=f"Active profile: **{profiles.label(active)}**")

        ui["copy"].click(
            fn=do_copy,
            inputs=[session, enabled, ad_enable, ad_skip, *widgets],
            outputs=[session, status],
            queue=False,
            show_progress=False,
        )

        def do_reset():
            gr.Info("Both profiles cleared; each will adopt the current settings")
            return (
                profiles.new_session(),
                gr.update(
                    value=f"Active profile: **{profiles.label(PROFILE_IMG2IMG)}**"
                ),
            )

        ui["reset"].click(
            fn=do_reset,
            inputs=[],
            outputs=[session, status],
            queue=False,
            show_progress=False,
        )

        def warn_on_inpaint_skip(state, split_on, skip):
            # Catches every route that can switch the flag on while the Inpaint
            # profile is active: the checkbox itself, a full preset, or an
            # infotext paste.
            if split_on and skip and profiles.normalize(state)["active"] == PROFILE_INPAINT:
                gr.Warning(
                    'ADetailer will not run: "Skip img2img" is not supported on '
                    "Inpaint. Turn it off for the Inpaint profile."
                )

        ad_skip.change(
            fn=warn_on_inpaint_skip,
            inputs=[session, enabled, ad_skip],
            outputs=[],
            queue=False,
            show_progress=False,
        )

        _log(f"img2img/Inpaint split wired to {len(tabs)} sub-tabs")
