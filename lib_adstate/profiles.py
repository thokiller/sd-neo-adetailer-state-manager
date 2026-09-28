"""Session-only img2img / Inpaint configuration split.

The webui shares a single ADetailer panel across every img2img sub-tab. This
module keeps one configuration per *family* of sub-tabs and swaps it in when the
user moves between families, so the plain img2img tab and the Inpaint tab behave
as if each had its own ADetailer.

Everything here is pure data: the state lives in a ``gr.State`` (one per browser
session) and is never written to disk, so a restart returns to plain ADetailer
defaults.
"""

from __future__ import annotations

from typing import Any

from . import (
    IMG2IMG_TAB_PROFILES,
    PROFILE_IMG2IMG,
    PROFILE_INPAINT,
    PROFILE_LABELS,
)


def profile_for_tab(elem_id: str) -> str | None:
    return IMG2IMG_TAB_PROFILES.get(elem_id)


def new_session() -> dict[str, Any]:
    return {
        "active": PROFILE_IMG2IMG,
        "configs": {PROFILE_IMG2IMG: None, PROFILE_INPAINT: None},
    }


def normalize(session: Any) -> dict[str, Any]:
    """Tolerate a missing or half-built session dict."""
    if not isinstance(session, dict):
        return new_session()

    active = session.get("active")
    if active not in (PROFILE_IMG2IMG, PROFILE_INPAINT):
        active = PROFILE_IMG2IMG

    configs = session.get("configs")
    if not isinstance(configs, dict):
        configs = {}

    return {
        "active": active,
        "configs": {
            PROFILE_IMG2IMG: configs.get(PROFILE_IMG2IMG),
            PROFILE_INPAINT: configs.get(PROFILE_INPAINT),
        },
    }


def other(profile: str) -> str:
    return PROFILE_INPAINT if profile == PROFILE_IMG2IMG else PROFILE_IMG2IMG


def label(profile: str) -> str:
    return PROFILE_LABELS.get(profile, profile)


def store(session: dict[str, Any], profile: str, config: dict[str, Any]) -> dict[str, Any]:
    session = normalize(session)
    session["configs"][profile] = config
    return session


def fetch(session: dict[str, Any], profile: str) -> dict[str, Any] | None:
    return normalize(session)["configs"].get(profile)


def switch(
    session: dict[str, Any],
    target: str,
    current_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Move to ``target``, saving ``current_config`` under the outgoing profile.

    Returns the updated session and the configuration to apply, or ``None`` when
    nothing needs to change (already on ``target``).

    The first time a profile is entered it inherits whatever is currently on
    screen, so enabling the split never wipes the user's settings.
    """
    session = normalize(session)
    active = session["active"]

    if active == target:
        # Keep the active profile's stored copy current so a later switch away
        # does not lose edits made in the meantime.
        session["configs"][active] = current_config
        return session, None

    session["configs"][active] = current_config
    session["active"] = target

    incoming = session["configs"].get(target)
    if incoming is None:
        incoming = seed_config(current_config, target)
        session["configs"][target] = incoming

    return session, incoming


def seed_config(config: dict[str, Any], target: str) -> dict[str, Any]:
    """Adapt an inherited configuration to the profile that is taking it over.

    ADetailer refuses to run at all on an inpaint tab while *Skip img2img* is
    on ("Skip img2img does not support Inpainting"), so carrying that flag over
    from the img2img profile would silently disable ADetailer the first time the
    Inpaint tab is opened. Seeding drops it; from then on the value is the
    user's to set.
    """
    if target != PROFILE_INPAINT or not isinstance(config, dict):
        return config

    if not config.get("skip_img2img"):
        return config

    seeded = dict(config)
    seeded["skip_img2img"] = False
    return seeded
