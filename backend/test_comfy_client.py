import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pdd_agent import comfy_client, creative


class _Response:
    content = b"new image"

    def raise_for_status(self):
        pass


class DownloadResultTests(unittest.TestCase):
    def test_scene_preflight_stops_before_download_or_identity_changes(self):
        with patch.object(comfy_client, "validate_reference_models", side_effect=RuntimeError("missing models")), patch.object(
            creative, "download_file"
        ) as download:
            with self.assertRaisesRegex(RuntimeError, "missing models"):
                creative.generate_scene_images(None, None, None, "unused")
            download.assert_not_called()

    def test_missing_models_stop_before_upload_or_queue(self):
        settings = SimpleNamespace(
            comfy_base_url="http://comfy", comfy_qwen_unet_name="missing-unet",
            comfy_qwen_clip_name="missing-clip", comfy_qwen_vae_name="missing-vae",
        )
        response = Mock()
        response.json.return_value = {}
        with patch.object(comfy_client.requests, "get", return_value=response), patch.object(
            comfy_client, "_upload_image"
        ) as upload, patch.object(comfy_client, "_queue_prompt") as queue:
            with self.assertRaisesRegex(RuntimeError, "missing-unet.*missing-clip.*missing-vae"):
                comfy_client.generate_image_with_references(
                    settings, "prompt", "negative", "missing.png", None, "output.png"
                )
            upload.assert_not_called()
            queue.assert_not_called()

    def test_proxy_bypass_includes_all_proxy_environment(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://invalid:9", "HTTPS_PROXY": "http://invalid:9",
                                     "ALL_PROXY": "http://invalid:9", "NO_PROXY": ""}, clear=True):
            session = comfy_client.requests.Session()
            options = session.merge_environment_settings("http://100.83.253.18:8189", dict(comfy_client._NO_PROXY), False, None, None)
            self.assertFalse(comfy_client.requests.utils.select_proxy("http://100.83.253.18:8189", options["proxies"]))

    def test_outpaint_padding_builds_masked_latent(self):
        settings = SimpleNamespace(
            comfy_qwen_unet_name="unet",
            comfy_qwen_clip_name="clip",
            comfy_qwen_vae_name="vae",
        )

        workflow = comfy_client._build_qwen_edit_workflow(
            settings, "persona.png", None, "prompt", "negative", 20, 2.5, 7, (91, 0, 92, 244)
        )

        self.assertEqual(workflow["118"]["class_type"], "ImagePadForOutpaint")
        self.assertEqual(workflow["118"]["inputs"]["bottom"], 244)
        self.assertEqual(workflow["88"]["class_type"], "VAEEncodeForInpaint")
        self.assertEqual(workflow["111"]["inputs"]["image1"], ["118", 0])

    def test_failed_atomic_replace_preserves_existing_image(self):
        result = {"outputs": {"9": {"images": [{"filename": "result.png"}]}}}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "result.png")
            with open(out_path, "wb") as f:
                f.write(b"old image")

            with patch.object(comfy_client.requests, "get", return_value=_Response()), patch.object(
                comfy_client.os, "replace", side_effect=OSError("replace failed")
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    comfy_client._download_result(SimpleNamespace(comfy_base_url="http://comfy"), result, out_path)

            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), b"old image")


if __name__ == "__main__":
    unittest.main()
