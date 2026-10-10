import unittest

from src.python.worker_client import cycles_gpu_setup_expression


class GpuRenderTests(unittest.TestCase):
    def test_cycles_gpu_setup_selects_a_detected_backend_and_never_silently_falls_back(self):
        expression = cycles_gpu_setup_expression()
        self.assertIn('("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")', expression)
        self.assertIn("preferences.get_devices()", expression)
        self.assertIn("device.type == selected_backend", expression)
        self.assertIn('scene.cycles.device = "GPU"', expression)
        self.assertIn("detected no supported Cycles GPU", expression)
        self.assertNotIn("--cycles-device", expression)


if __name__ == "__main__":
    unittest.main()
