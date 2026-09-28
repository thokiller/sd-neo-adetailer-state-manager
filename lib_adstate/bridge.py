"""Translating between saved snapshots and live ADetailer components.

The important detail: ADetailer-Neo does not read its widgets when generating.
``AfterDetailerScript.process`` only receives ``[ad_enable, ad_skip_img2img,
state_0, state_1, ...]``, where each state is a ``gr.State`` dict kept in sync by
one ``.change()`` handler per widget.

That is why the previous JavaScript prototype appeared to load a preset but then
generated with the old (usually disabled) configuration: writing the DOM never
reached the state. Everything here therefore writes the widgets *and* the state
dicts in the same handler.
"""

from __future__ import annotations

from typing import Any

from .registry import all_args


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (list,)):
        return [_json_safe(v) for v in value]
    return value


def attrs() -> tuple[str, ...]:
    return all_args().attrs


def defaults() -> dict[str, Any]:
    from lib_adetailer.args import ADetailerArgs

    model = ADetailerArgs()
    return {attr: getattr(model, attr) for attr in attrs()}


def snapshot_from_values(values: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-serialisable snapshot of one ADetailer sub-tab."""
    return {attr: _json_safe(values.get(attr)) for attr in attrs()}


def _choice_values(component: Any) -> list[Any] | None:
    choices = getattr(component, "choices", None)
    if not choices:
        return None

    # Gradio 4 stores choices as (label, value) pairs, but extensions sometimes
    # still pass bare strings.
    return [c[1] if isinstance(c, (tuple, list)) and len(c) == 2 else c for c in choices]


def sanitize(
    raw: dict[str, Any],
    widgets: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce a stored snapshot into values this installation can actually use.

    Returns the cleaned values plus human-readable notes about anything that had
    to be changed (missing detection model, checkpoint from another machine, a
    value outside the allowed range, ...).
    """
    from lib_adetailer.args import ADetailerArgs

    known = set(attrs())
    base = dict(fallback) if fallback else defaults()

    notes: list[str] = []
    candidate = dict(base)

    for key, value in raw.items():
        if key in known:
            candidate[key] = value
        elif key != "is_api":
            notes.append(f'ignored unknown setting "{key}"')

    # Validate through ADetailer's own model, dropping any field it rejects so a
    # single bad value cannot make the whole preset unloadable.
    for _ in range(len(known) + 1):
        try:
            model = ADetailerArgs(**candidate)
        except Exception as exc:
            rejected = _rejected_fields(exc) & known
            if not rejected:
                notes.append(f"preset could not be validated ({exc}); used defaults")
                candidate = dict(base)
                break

            for field in sorted(rejected):
                notes.append(f'"{field}" was invalid; kept {base[field]!r}')
                candidate[field] = base[field]
            continue
        else:
            candidate = {attr: getattr(model, attr) for attr in attrs()}
            break

    # Values that exist in the preset but not on this machine (models, VAEs,
    # samplers, ControlNet entries) would otherwise silently blank the dropdown.
    for attr, component in widgets.items():
        if attr not in candidate:
            continue

        allowed = _choice_values(component)
        if allowed is None:
            continue

        value = candidate[attr]
        if value in allowed or value is None:
            continue

        notes.append(f'"{value}" is not available for {attr}; kept {base[attr]!r}')
        candidate[attr] = base[attr]

    return candidate, notes


def _rejected_fields(exc: Exception) -> set[str]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return set()

    try:
        entries = errors()
    except Exception:
        return set()

    fields: set[str] = set()
    for entry in entries:
        loc = entry.get("loc") or ()
        if loc and isinstance(loc[0], str):
            fields.add(loc[0])
    return fields


def state_dict(values: dict[str, Any]) -> dict[str, Any]:
    """The exact shape ADetailer keeps in its per-tab ``gr.State``.

    ``is_api`` is deliberately absent: ADetailer strips it on every widget change
    and re-adds it when the Generate button is pressed.
    """
    return {attr: values[attr] for attr in attrs()}


def widget_updates(values: dict[str, Any], widgets: dict[str, Any]) -> dict[str, Any]:
    """``{attr: gr.update(...)}`` for every widget we were able to locate."""
    import gradio as gr

    updates: dict[str, Any] = {}
    for attr in widgets:
        value = values.get(attr)

        # The ControlNet guidance control is a RangeSlider and needs a tuple.
        if attr == "ad_controlnet_guidance_start_end" and isinstance(value, list):
            value = tuple(value)

        updates[attr] = gr.update(value=value)

    return updates
