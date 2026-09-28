# ADetailer State Manager

Save, load and split [ADetailer-Neo](https://github.com/Haoming02/ADetailer-Neo)
configurations in SD WebUI Forge Neo.

This extension sits *on top of* ADetailer-Neo and never modifies it, so ADetailer
stays updatable. If ADetailer-Neo is not installed the extension quietly does
nothing.

## Requirements

- **SD WebUI Forge Neo** (or a fork with the same extension API)
- **[ADetailer-Neo](https://github.com/Haoming02/ADetailer-Neo)** — required.
  This extension reads ADetailer's own argument definitions and writes its
  internal state, so it cannot work without it.

No extra Python packages, so there is no `install.py` and nothing to pip-install.

## Installation

In the webui: **Extensions → Install from URL**, paste the repository URL, then
**Apply and restart UI**. Or clone it manually:

```
cd extensions
git clone <repository-url> ADetailer-Neo-StateManager
```

Install **ADetailer-Neo** first if you do not already have it. If it is missing,
the webui still starts normally and the panel simply does not appear; the
console prints a line starting with `[ADetailer State Manager] disabled -`.

> **Keep the folder name.** This webui derives an extension's canonical name
> from its directory, and `metadata.ini` asks to be loaded after `adetailer-neo`.
> Keeping the default clone names (`ADetailer-Neo-StateManager` and
> `ADetailer-Neo`) keeps that ordering hint working. Nothing breaks if you rename
> them — UI order comes from `sorting_priority`, not the folder name.

## Features

### Tab presets

Save the settings of a single ADetailer sub-tab (1st, 2nd, ...) and load them
back into any sub-tab, in either txt2img or img2img.

### Full presets

Save every ADetailer sub-tab at once, together with the main **ADetailer** toggle
and **Skip img2img**. Loading restores all of them.

### img2img / Inpaint split

The webui shows one ADetailer panel for all of img2img, so the plain img2img tab
and the Inpaint tab normally fight over the same settings. Enable
**Separate ADetailer config for img2img and Inpaint** and each keeps its own:

| Profile     | Sub-tabs                                         |
| ----------- | ------------------------------------------------ |
| **img2img** | img2img, Sketch, Batch                           |
| **Inpaint** | Inpaint, Inpaint sketch, Inpaint upload          |

Switching between the two families swaps the whole ADetailer configuration. The
first time you enter a profile it inherits whatever is currently on screen, so
turning the split on never discards your settings.

This split is **session only** — it lives in the browser session and is not
written to disk. Restarting the webui returns to plain ADetailer behaviour. Use a
full preset if you want a setup to survive a restart.

There are also buttons to copy the active profile onto the other one, and to
reset both.

## Behaviour guarantees

- **Saved presets survive a browser reload.** The preset lists are re-read from
  disk every time the page loads, so a preset saved in one sitting is still
  listed after F5 - and a preset saved from img2img shows up in txt2img too.
- **ADetailer stays enabled in both profiles.** The split only swaps settings;
  it never switches ADetailer off. One exception is deliberate: see below.
- **Skip img2img is cleared when the Inpaint profile is first seeded.**
  ADetailer refuses to run on an inpaint tab while that flag is on (it prints
  *"Skip img2img" does not support Inpainting* and disables itself). Since the
  Inpaint profile starts as a copy of the img2img one, inheriting the flag would
  silently kill ADetailer the first time you open Inpaint. It is therefore
  dropped once, with a notice; after that the value is yours to set, and a
  warning appears if it is ever switched back on while Inpaint is active.

- **Loading is a one-shot push.** After a preset is applied, the ADetailer
  toggle, the per-tab *Enable* checkboxes and every other control behave exactly
  as they normally do. You can switch ADetailer off right after loading.
- **Presets never change on their own.** Editing the UI after a load does not
  write back to the preset file. A preset only changes when you explicitly save
  over the same name.
- **Presets are portable.** One shared library is listed in txt2img and img2img,
  and any preset can be loaded into any sub-tab of either.
- **Unavailable values are reported, not silently dropped.** If a preset refers
  to a detection model, checkpoint, VAE, sampler or ControlNet entry that this
  installation does not have, the current value is kept and a warning lists what
  was adjusted.
- **The number of sub-tabs may change.** ADetailer's *Max Tabs*
  (`ad_max_models`) is a user setting, so it can differ between installations
  and can be changed at any time via Settings → ADetailer → Reload UI. Both are
  handled:
  - Changing it and reloading the UI re-binds everything automatically; the tab
    dropdowns resize to match.
  - Loading a preset saved with **more** tabs than are shown ignores the extras
    and says so. Loading one with **fewer** tabs leaves the remaining sub-tabs
    untouched and says so.
- **Every ADetailer setting is covered.** Presets store all 39 arguments per
  sub-tab, which is ADetailer's complete argument set: the main controls plus
  everything under *Detection*, *Mask Preprocessing*, *Inpaint Parameters* and
  *ControlNet*. ADetailer builds those four sections into one shared widget
  object and this extension iterates the same `ALL_ARGS` list, so the two cannot
  drift apart.

## Interaction with the "Send to" and paste buttons

- The gallery **🖼️ Send to img2img** and **🎨️ Send to inpaint** buttons never
  touch the ADetailer configuration. They only paste fields a script has
  registered in `paste_field_names`, and ADetailer registers none. Your
  per-sub-tab ADetailer setup therefore survives sending an image from txt2img
  to img2img, and from img2img to Inpaint.
- The toprow **↙ Read generation parameters** button and the **PNG Info** tab's
  send buttons use a different, unfiltered code path and *do* overwrite the
  ADetailer configuration with whatever is in the infotext. That is stock WebUI
  behaviour and is usually what you want when recreating an old image — just be
  aware it replaces the live settings of the sub-tab you are on. Re-loading a
  preset restores them.

## Storage

Presets are individual JSON files, so there is no limit on how many you keep:

```
<models dir>/adetailer-presets/
    tab/<name>.json     # single sub-tab
    full/<name>.json    # every sub-tab + main toggle + Skip img2img
```

`<models dir>` is the same directory the WebUI uses for checkpoints, so it
follows `--data-dir` and `--models-dir`. If you point several installs at one
shared models drive, they share a preset library too.

Back them up or move them between installs by copying the files. Names are
sanitized into safe filenames, so `face / strong?` is stored as `face strong`.
Hand-edited files are fine, including UTF-8 with a byte order mark (what Notepad
and PowerShell write by default).

Presets deliberately live **outside** the extension folder, so updating,
reinstalling or removing the extension never touches your library. Uninstalling
leaves `adetailer-presets/` behind; delete it by hand if you want it gone.

The models directory is used because the stock WebUI `.gitignore` excludes
`/models/**/*`. Presets therefore survive a `git clean -fd` while updating the
WebUI, which would delete them from an ordinary folder such as `presets/`.

## Why a Python extension and not JavaScript

ADetailer-Neo does not read its widgets when generating. `process()` only
receives `[ad_enable, ad_skip_img2img, state_0, state_1, ...]`, where each state
is a `gr.State` dictionary kept in sync by one Gradio `.change()` handler per
widget.

A JavaScript extension that writes DOM values therefore *appears* to load a
preset while ADetailer keeps generating with the previous — usually disabled —
configuration. This extension writes the widgets **and** those state
dictionaries in the same handler, plus the hidden checkbox behind the ADetailer
`InputAccordion`, which is what makes loading actually take effect.

## Development

```
cd extensions/ADetailer-Neo-StateManager
../../venv/Scripts/python.exe -m unittest discover -s tests -v
```

The tests cover preset storage and the profile-switching logic; neither needs a
running webui or ADetailer installed.

### How it stays decoupled

The extension is entirely self-contained — one folder, no changes to ADetailer
or to any webui core file. It only ever *reads* from them:

| Import                   | Why                                                     |
| ------------------------ | ------------------------------------------------------- |
| `modules.*`              | script API, callbacks, `FormRow`, data path             |
| `lib_adetailer.args`     | the authoritative argument list and its validation model |
| `gradio`                 | UI                                                      |

Because the argument list comes from ADetailer itself rather than a copy, an
ADetailer update that adds or renames a setting is picked up automatically. If a
future version changes the parts this relies on — the `script_{tab}_adetailer_*`
element ids, or the per-tab `gr.State` objects — the registry refuses to bind,
logs `[ADetailer State Manager] disabled - ...` and leaves the webui working
normally rather than half-wired.
