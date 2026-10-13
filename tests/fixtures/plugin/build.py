from pathlib import Path
from zipfile import ZipFile

Path('build').mkdir(exist_ok=True)
with ZipFile('build/plugin.zip', 'w') as archive:
    archive.write('plugin.cjs')
with ZipFile('build/plugin.zip') as archive:
    assert archive.namelist() == ['plugin.cjs']
