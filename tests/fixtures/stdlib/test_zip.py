import io
import unittest
from zipfile import ZipFile


class ZipTests(unittest.TestCase):
    def test_roundtrip(self):
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("value.txt", "42")
        with ZipFile(stream) as archive:
            self.assertEqual(archive.read("value.txt"), b"42")
