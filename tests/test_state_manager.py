"""Offline tests for the parts that do not need a running webui.

Run from the extension folder::

    ..\\..\\venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib_adstate import PROFILE_IMG2IMG, PROFILE_INPAINT, profiles, registry, store  # noqa: E402


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="adstate-test-"))
        store.set_base_dir(self.root)
        self.addCleanup(store.set_base_dir, None)
        self.addCleanup(shutil.rmtree, self.root, True)


class TestSanitizeName(StoreTestCase):
    def test_keeps_usable_names(self):
        cases = {
            "face": "face",
            "  spaced   out  ": "spaced out",
            "a/b\\c:d*e?f": "a b c d e f",
            "trailing...": "trailing",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(store.sanitize_name(raw), expected)

    def test_rejects_empty(self):
        for raw in ("", "   ", "///", "..."):
            with self.subTest(raw=raw):
                with self.assertRaises(store.PresetError):
                    store.sanitize_name(raw)

    def test_rejects_non_text(self):
        with self.assertRaises(store.PresetError):
            store.sanitize_name(None)

    def test_avoids_reserved_device_names(self):
        self.assertEqual(store.sanitize_name("CON"), "CON_")
        self.assertEqual(store.sanitize_name("nul"), "nul_")

    def test_is_length_capped(self):
        self.assertEqual(len(store.sanitize_name("x" * 400)), 96)


class TestPresetIO(StoreTestCase):
    def test_save_then_load_roundtrip(self):
        store.save_preset("tab", "my preset", {"tab": {"ad_model": "face_yolov8n.pt"}})

        document = store.load_preset("tab", "my preset")

        self.assertEqual(document["tab"]["ad_model"], "face_yolov8n.pt")
        self.assertEqual(document["kind"], "tab")
        self.assertEqual(document["name"], "my preset")
        self.assertEqual(document["schema"], store.SCHEMA_VERSION)
        self.assertIn("saved_at", document)

    def test_save_uses_sanitized_filename(self):
        store.save_preset("full", "bad/name", {"tabs": []})

        self.assertTrue((self.root / "full" / "bad name.json").is_file())

    def test_list_presets_is_sorted_case_insensitively(self):
        for name in ("beta", "Alpha", "gamma"):
            store.save_preset("tab", name, {"tab": {}})

        self.assertEqual(store.list_presets("tab"), ["Alpha", "beta", "gamma"])

    def test_list_presets_empty_when_missing(self):
        self.assertEqual(store.list_presets("tab"), [])
        self.assertEqual(store.list_presets("full"), [])

    def test_kinds_have_separate_namespaces(self):
        store.save_preset("tab", "shared", {"tab": {}})

        self.assertEqual(store.list_presets("tab"), ["shared"])
        self.assertEqual(store.list_presets("full"), [])

    def test_exists_and_overwrite(self):
        self.assertFalse(store.exists("tab", "one"))

        store.save_preset("tab", "one", {"tab": {"ad_confidence": 0.3}})
        self.assertTrue(store.exists("tab", "one"))

        store.save_preset("tab", "one", {"tab": {"ad_confidence": 0.9}})
        self.assertEqual(store.load_preset("tab", "one")["tab"]["ad_confidence"], 0.9)
        self.assertEqual(store.list_presets("tab"), ["one"])

    def test_delete_preset(self):
        store.save_preset("tab", "gone", {"tab": {}})
        store.delete_preset("tab", "gone")

        self.assertEqual(store.list_presets("tab"), [])
        with self.assertRaises(store.PresetError):
            store.delete_preset("tab", "gone")

    def test_load_missing_preset(self):
        with self.assertRaises(store.PresetError):
            store.load_preset("tab", "nope")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(store.PresetError):
            store.kind_dir("bogus")

    def test_save_leaves_no_temp_file(self):
        store.save_preset("tab", "clean", {"tab": {}})

        self.assertEqual(
            [p.name for p in (self.root / "tab").iterdir()], ["clean.json"]
        )

    def _tamper(self, name, **changes):
        path = self.root / "tab" / f"{name}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document.update(changes)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_load_rejects_wrong_kind(self):
        store.save_preset("tab", "mismatch", {"tab": {}})
        self._tamper("mismatch", kind="full")

        with self.assertRaises(store.PresetError):
            store.load_preset("tab", "mismatch")

    def test_load_rejects_newer_schema(self):
        store.save_preset("tab", "future", {"tab": {}})
        self._tamper("future", schema=store.SCHEMA_VERSION + 1)

        with self.assertRaises(store.PresetError):
            store.load_preset("tab", "future")

    def test_load_rejects_corrupt_json(self):
        path = self.root / "tab" / "broken.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(store.PresetError):
            store.load_preset("tab", "broken")

    def test_load_accepts_a_byte_order_mark(self):
        """Notepad and PowerShell write UTF-8 with a BOM by default."""
        store.save_preset("tab", "bom", {"tab": {"ad_model": "face"}})
        path = store.preset_path("tab", "bom")
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8-sig")

        document = store.load_preset("tab", "bom")

        self.assertEqual(document["tab"]["ad_model"], "face")


def _config(marker):
    return {"enable": True, "skip_img2img": False, "tabs": [{"ad_model": marker}]}


class _FakeArgs:
    attrs = ("ad_model", "ad_prompt")


class _FakeComponent:
    def __init__(self, elem_id):
        self.elem_id = elem_id


class TestRegistryTabCount(unittest.TestCase):
    """"Max Tabs" (``ad_max_models``) is a user setting and can change."""

    def setUp(self):
        self.count = 2
        self.reg = registry.Registry()

        original_args = registry.all_args
        original_num = registry.num_models
        registry.all_args = lambda: _FakeArgs
        registry.num_models = lambda: self.count
        self.addCleanup(setattr, registry, "all_args", original_args)
        self.addCleanup(setattr, registry, "num_models", original_num)

    def _build_ui(self):
        """Feed the registry every widget ADetailer would create."""
        for tabname in ("txt2img", "img2img"):
            for n in range(self.count):
                for attr in _FakeArgs.attrs:
                    eid = registry.elem_id(attr, n, tabname)
                    self.reg.observe(_FakeComponent(eid))

    def test_matches_widgets_for_the_current_count(self):
        self._build_ui()

        self.assertTrue(self.reg.is_complete("txt2img"))
        self.assertEqual(self.reg.missing("img2img"), [])

    def test_more_tabs_after_reload_are_picked_up(self):
        self._build_ui()

        # The user raises Max Tabs and clicks "Reload UI".
        self.count = 4
        self.reg.reset()
        self._build_ui()

        self.assertTrue(self.reg.is_complete("txt2img"))
        self.assertTrue(self.reg.is_complete("img2img"))

    def test_fewer_tabs_after_reload_drop_stale_widgets(self):
        self.count = 4
        self._build_ui()

        self.count = 2
        self.reg.reset()
        self._build_ui()

        self.assertTrue(self.reg.is_complete("txt2img"))
        self.assertIsNone(self.reg.widget("txt2img", 3, "ad_model"))

    def test_reset_clears_everything(self):
        self._build_ui()
        self.reg.reset()

        self.assertEqual(self.reg.widgets, {})
        self.assertEqual(self.reg.img2img_tabs, {})
        self.assertFalse(self.reg.is_complete("txt2img"))

    def test_count_change_without_reset_still_rebuilds(self):
        """A missed reset must not permanently wedge the registry."""
        self._build_ui()

        self.count = 4
        self._build_ui()

        self.assertTrue(self.reg.is_complete("txt2img"))


class TestProfiles(unittest.TestCase):
    def test_seeding_inpaint_drops_skip_img2img(self):
        """ADetailer refuses to run on Inpaint while Skip img2img is on."""
        session = profiles.new_session()
        img2img_cfg = {
            "enable": True,
            "skip_img2img": True,
            "tabs": [{"ad_model": "body"}],
        }

        session, incoming = profiles.switch(session, PROFILE_INPAINT, img2img_cfg)

        self.assertIsNotNone(incoming)
        self.assertFalse(incoming["skip_img2img"])
        self.assertTrue(incoming["enable"])
        self.assertEqual(incoming["tabs"], [{"ad_model": "body"}])
        self.assertFalse(session["configs"][PROFILE_INPAINT]["skip_img2img"])

    def test_seeding_inpaint_does_not_mutate_the_img2img_config(self):
        session = profiles.new_session()
        img2img_cfg = {"enable": True, "skip_img2img": True, "tabs": []}

        session, _ = profiles.switch(session, PROFILE_INPAINT, img2img_cfg)

        self.assertTrue(img2img_cfg["skip_img2img"])
        self.assertTrue(session["configs"][PROFILE_IMG2IMG]["skip_img2img"])

    def test_seeding_img2img_keeps_skip_img2img(self):
        session = profiles.new_session()
        session["active"] = PROFILE_INPAINT
        inpaint_cfg = {"enable": True, "skip_img2img": True, "tabs": []}

        _, incoming = profiles.switch(session, PROFILE_IMG2IMG, inpaint_cfg)

        self.assertTrue(incoming["skip_img2img"])

    def test_skip_is_only_cleared_on_the_first_visit(self):
        """Afterwards the flag is the user's to set, even on Inpaint."""
        session = profiles.new_session()
        # First visit seeds the Inpaint profile.
        session, _ = profiles.switch(session, PROFILE_INPAINT, _config("a"))

        # While on Inpaint the user deliberately turns Skip img2img on; leaving
        # the tab stores that choice.
        deliberate = {"enable": True, "skip_img2img": True, "tabs": [{"ad_model": "x"}]}
        session, _ = profiles.switch(session, PROFILE_IMG2IMG, deliberate)

        # Coming back must hand the flag back untouched.
        session, incoming = profiles.switch(session, PROFILE_INPAINT, _config("b"))

        self.assertTrue(incoming["skip_img2img"])

    def test_new_session_starts_on_img2img(self):
        session = profiles.new_session()

        self.assertEqual(session["active"], PROFILE_IMG2IMG)
        self.assertEqual(
            session["configs"], {PROFILE_IMG2IMG: None, PROFILE_INPAINT: None}
        )

    def test_normalize_repairs_bad_sessions(self):
        for broken in (None, "nonsense", 42, {}, {"active": "???"}):
            with self.subTest(broken=broken):
                session = profiles.normalize(broken)

                self.assertEqual(session["active"], PROFILE_IMG2IMG)
                self.assertEqual(
                    set(session["configs"]), {PROFILE_IMG2IMG, PROFILE_INPAINT}
                )

    def test_profile_for_tab(self):
        expected = {
            "img2img_img2img_tab": PROFILE_IMG2IMG,
            "img2img_img2img_sketch_tab": PROFILE_IMG2IMG,
            "img2img_batch_tab": PROFILE_IMG2IMG,
            "img2img_inpaint_tab": PROFILE_INPAINT,
            "img2img_inpaint_sketch_tab": PROFILE_INPAINT,
            "img2img_inpaint_upload_tab": PROFILE_INPAINT,
            "txt2img_whatever": None,
        }
        for elem_id, profile in expected.items():
            with self.subTest(elem_id=elem_id):
                self.assertEqual(profiles.profile_for_tab(elem_id), profile)

    def test_other(self):
        self.assertEqual(profiles.other(PROFILE_IMG2IMG), PROFILE_INPAINT)
        self.assertEqual(profiles.other(PROFILE_INPAINT), PROFILE_IMG2IMG)

    def test_switch_to_same_profile_changes_nothing_visible(self):
        session = profiles.new_session()

        session, incoming = profiles.switch(session, PROFILE_IMG2IMG, _config("a"))

        self.assertIsNone(incoming)
        self.assertEqual(session["configs"][PROFILE_IMG2IMG], _config("a"))

    def test_first_switch_inherits_current_settings(self):
        session = profiles.new_session()

        session, incoming = profiles.switch(session, PROFILE_INPAINT, _config("a"))

        self.assertEqual(session["active"], PROFILE_INPAINT)
        self.assertEqual(incoming, _config("a"))
        self.assertEqual(session["configs"][PROFILE_IMG2IMG], _config("a"))

    def test_switching_back_restores_the_other_profile(self):
        session = profiles.new_session()

        session, _ = profiles.switch(session, PROFILE_INPAINT, _config("i2i"))
        session, incoming = profiles.switch(
            session, PROFILE_IMG2IMG, _config("inpaint")
        )

        self.assertEqual(incoming, _config("i2i"))
        self.assertEqual(session["configs"][PROFILE_INPAINT], _config("inpaint"))
        self.assertEqual(session["active"], PROFILE_IMG2IMG)

    def test_edits_within_a_profile_are_kept_on_switch_away(self):
        session = profiles.new_session()
        session, _ = profiles.switch(session, PROFILE_INPAINT, _config("first"))
        session, _ = profiles.switch(
            session, PROFILE_IMG2IMG, _config("inpaint edits")
        )

        session, incoming = profiles.switch(
            session, PROFILE_INPAINT, _config("i2i edits")
        )

        self.assertEqual(incoming, _config("inpaint edits"))
        self.assertEqual(session["configs"][PROFILE_IMG2IMG], _config("i2i edits"))

    def test_store_and_fetch(self):
        session = profiles.store(profiles.new_session(), PROFILE_INPAINT, _config("x"))

        self.assertEqual(profiles.fetch(session, PROFILE_INPAINT), _config("x"))
        self.assertIsNone(profiles.fetch(session, PROFILE_IMG2IMG))


if __name__ == "__main__":
    unittest.main()
