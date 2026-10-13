import sys
import unittest


class RuntimeTests(unittest.TestCase):
    def test_declared_patch_floor_and_minor_ceiling(self):
        self.assertGreaterEqual(sys.version_info[:3], (3, 14, 5))
        self.assertLess(sys.version_info[:2], (3, 15))
