import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import zipfile
import six


class ArchiveTests(unittest.TestCase):
    def test_archive_tool_and_small_fixture(self):
        executable = shutil.which("7zz")
        self.assertIsNotNone(executable, "7zz required: system-packages: 7zip-standalone; never skip")
        self.assertIsInstance("42", six.string_types)
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "small.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("answer.txt", "42")
            result = subprocess.run([executable, "t", str(archive)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
