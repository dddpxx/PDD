import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from pdd_agent import creative, personas


class PersonaViewTests(unittest.TestCase):
    def test_identity_output_is_normalized_to_exact_3_by_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.png"
            Image.new("RGB", (880, 1184), (90, 120, 150)).save(output)

            personas._normalize_identity_view(os.fspath(output))

            with Image.open(output) as image:
                self.assertEqual(image.size, (768, 1024))

    def test_identity_output_trims_generated_gray_border(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.png"
            image = Image.new("RGB", (768, 1024), (128, 128, 128))
            image.paste((200, 150, 100), (75, 0, 700, 807))
            image.save(output)

            personas._normalize_identity_view(os.fspath(output))

            with Image.open(output) as image:
                self.assertEqual(image.size, (768, 1024))
                self.assertGreater(image.getpixel((0, 1023))[0], 180)

    def test_profile_output_crops_lower_legs_at_knees(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output.png"
            image = Image.new("RGB", (768, 1024), (80, 120, 160))
            image.paste((220, 40, 40), (0, 800, 768, 1024))
            image.save(output)

            personas._crop_profile_to_knees(os.fspath(output))

            with Image.open(output) as image:
                self.assertEqual(image.size, (768, 1024))
                self.assertLess(image.getpixel((384, 1023))[0], 100)

    def test_identity_reference_is_cropped_and_extended_to_3_by_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            target = Path(tmp) / "reference.png"
            Image.new("RGB", (1200, 1200), (180, 100, 80)).save(source)

            personas._prepare_identity_reference(os.fspath(source), os.fspath(target))

            with Image.open(target) as image:
                self.assertEqual(image.size, (768, 1024))
                self.assertEqual(image.getpixel((384, 0)), (180, 100, 80))
                self.assertEqual(image.getpixel((384, 1023)), (128, 128, 128))

    def test_scene_cache_key_changes_with_persona_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "FRONT_000.png"
            reference.write_bytes(b"first")
            first = creative._scene_output_filename("帅帅", os.fspath(reference), "正面")
            reference.write_bytes(b"second")
            second = creative._scene_output_filename("帅帅", os.fspath(reference), "正面")

        self.assertNotEqual(first, second)
        self.assertIn("FRONT_000", second)

    def test_prompt_and_product_changes_do_not_reuse_old_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference, product = Path(tmp) / "person.png", Path(tmp) / "product.png"
            reference.write_bytes(b"same person")
            product.write_bytes(b"gray briefs")
            def filename(prompt):
                return creative._scene_output_filename("肌肉男", str(reference), "正面", str(product), prompt)
            first = filename("rough skin")
            self.assertEqual(first, filename("rough skin"))
            self.assertNotEqual(first, filename("different lighting"))
            product.write_bytes(b"different garment")
            self.assertNotEqual(first, filename("rough skin"))

    def test_nested_persona_source_wins_over_legacy_flat_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "帅帅" / "帅帅.png"
            nested.parent.mkdir()
            nested.write_bytes(b"image")

            with patch.object(personas, "PERSONA_DIR", str(root)):
                self.assertEqual(personas.persona_path("帅帅"), os.fspath(nested))

    def test_missing_back_view_does_not_fall_back_to_front(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "帅帅" / "帅帅.png"
            front = root / "帅帅" / "identity" / "FRONT_000.png"
            front.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            front.write_bytes(b"front")

            with patch.object(personas, "PERSONA_DIR", str(root)):
                self.assertEqual(personas.persona_reference_path("帅帅", "FRONT_000"), os.fspath(front))
                with self.assertRaisesRegex(FileNotFoundError, "BACK_180"):
                    personas.persona_reference_path("帅帅", "BACK_180")

    def test_missing_identity_does_not_generate_a_new_person(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            personas, "PERSONA_DIR", tmp
        ), patch.object(personas, "_generate_one") as generate:
            with self.assertRaisesRegex(FileNotFoundError, "不会自动生成"):
                personas.get_or_create_persona("肌肉男", "prompt", object())
            generate.assert_not_called()

    def test_view_prompt_file_is_split_into_one_prompt_per_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "人物共用总提示词.txt").write_text("same person", encoding="utf-8")
            (root / "附加提示词.txt").write_text("identity drift", encoding="utf-8")
            (root / "人物六视图.txt").write_text(
                "[FRONT_000]\nprompt = front view\n\n[BACK_180]\nprompt = rear view\n",
                encoding="utf-8",
            )

            with patch.object(personas, "PERSONA_DIR", str(root)):
                common, negative, views = personas.load_identity_prompts()

            self.assertEqual(common, "same person")
            self.assertEqual(negative, "identity drift")
            self.assertEqual(views, [("FRONT_000", "front view"), ("BACK_180", "rear view")])

    def test_generation_uses_one_view_prompt_and_single_identity_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "帅帅" / "帅帅.png"
            source.parent.mkdir()
            Image.new("RGB", (100, 100)).save(source)
            (root / "人物共用总提示词.txt").write_text("same identity", encoding="utf-8")
            (root / "附加提示词.txt").write_text("identity drift", encoding="utf-8")
            (root / "人物六视图.txt").write_text(
                "[FRONT_000]\nprompt = front instruction\n\n[BACK_180]\nprompt = rear instruction\n",
                encoding="utf-8",
            )
            edit_calls = []

            def generate_edit(_settings, prompt, negative, persona_path, product_path, out_path, **kwargs):
                with Image.open(persona_path) as image:
                    expected_size = (585, 780) if kwargs.get("outpaint_padding") else (768, 1024)
                    self.assertEqual(image.size, expected_size)
                Image.new("RGB", (768, 1024)).save(out_path)
                edit_calls.append(
                    (prompt, negative, persona_path, product_path, kwargs["seed"], kwargs.get("outpaint_padding"))
                )

            with patch.object(personas, "PERSONA_DIR", str(root)), patch.object(
                personas.comfy_client, "generate_image_with_references", side_effect=generate_edit
            ):
                personas.generate_identity_views("帅帅", object(), seed=7)

            self.assertEqual(len(edit_calls), 3)
            self.assertIn("front instruction", edit_calls[0][0])
            self.assertNotIn("rear instruction", edit_calls[0][0])
            self.assertNotEqual(edit_calls[0][2], os.fspath(source))
            self.assertEqual(edit_calls[0][3:], (None, 7, None))
            self.assertIn("rear instruction", edit_calls[1][0])
            self.assertNotIn("front instruction", edit_calls[1][0])
            self.assertEqual(
                edit_calls[1][2:], (os.fspath(root / "帅帅" / "identity" / "FRONT_000.png"), None, 8, None)
            )
            self.assertIn("rear instruction", edit_calls[2][0])
            self.assertEqual(edit_calls[2][3:], (None, 8, (91, 0, 92, 244)))
            self.assertFalse(os.path.exists(edit_calls[0][2]))
            self.assertFalse(os.path.exists(edit_calls[2][2]))

    def test_square_identity_output_is_regenerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "帅帅" / "帅帅.png"
            output = root / "帅帅" / "identity" / "FRONT_000.png"
            output.parent.mkdir(parents=True)
            Image.new("RGB", (100, 100)).save(source)
            Image.new("RGB", (1024, 1024)).save(output)
            (root / "人物共用总提示词.txt").write_text("same identity", encoding="utf-8")
            (root / "附加提示词.txt").write_text("identity drift", encoding="utf-8")
            (root / "人物六视图.txt").write_text("[FRONT_000]\nprompt = front\n", encoding="utf-8")
            calls = []

            def generate_edit(_settings, _prompt, _negative, _persona, _product, out_path, **_kwargs):
                calls.append(out_path)
                Image.new("RGB", (768, 1024)).save(out_path)

            with patch.object(personas, "PERSONA_DIR", str(root)), patch.object(
                personas.comfy_client, "generate_image_with_references", side_effect=generate_edit
            ):
                personas.generate_identity_views("帅帅", object(), seed=7)

            self.assertEqual(len(calls), 1)
            with Image.open(output) as image:
                self.assertEqual(image.size, (768, 1024))

    def test_side_views_are_generated_independently_with_distinct_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "帅帅" / "帅帅.png"
            source.parent.mkdir()
            Image.new("RGB", (100, 100)).save(source)
            (root / "人物共用总提示词.txt").write_text("same identity", encoding="utf-8")
            (root / "附加提示词.txt").write_text("identity drift", encoding="utf-8")
            (root / "人物六视图.txt").write_text(
                "[LEFT_090]\nprompt = left\n\n[RIGHT_090]\nprompt = right\n",
                encoding="utf-8",
            )
            edit_calls = []

            def generate_edit(_settings, prompt, _negative, _persona, _product, out_path, **_kwargs):
                edit_calls.append((prompt, _kwargs['seed']))
                Image.new("RGB", (768, 1024)).save(out_path)
                with Image.open(out_path) as image:
                    image.putpixel((84, 0), (255, 0, 0))
                    image.save(out_path)

            with patch.object(personas, "PERSONA_DIR", str(root)), patch.object(
                personas.comfy_client, "generate_image_with_references", side_effect=generate_edit
            ):
                personas.generate_identity_views("帅帅", object(), seed=7)

            right = root / "帅帅" / "identity" / "RIGHT_090.png"
            self.assertEqual(len(edit_calls), 4)
            self.assertIn('left', edit_calls[0][0])
            self.assertIn('right', edit_calls[2][0])
            self.assertEqual([call[1] for call in edit_calls], [7, 7, 8, 8])
            with Image.open(right) as image:
                self.assertEqual(image.size, (768, 1024))
                self.assertGreater(image.getpixel((0, 0))[0], 200)
