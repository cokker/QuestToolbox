"""Assemble a Windows portable folder from official CPython/PySide wheels.

Usage:
  python scripts/package_portable.py --python-zip ../python-embed.zip \
    --wheels ../win-wheels --launcher ../QuestToolbox.exe --output ../deliverables

Use only trusted official input archives. The launcher is built from launcher.c
and launcher.rc; no cross-compilation of Python extension modules is attempted.
"""
import argparse
from pathlib import Path
import shutil
import zipfile
import sys


def extract(archive, destination):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if not (destination/item.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError('Invalid archive path')
        z.extractall(destination)


def main():
    parser=argparse.ArgumentParser()
    for arg in ('python-zip','wheels','launcher','output'):
        parser.add_argument('--'+arg,required=True,type=Path)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from quest_toolbox import __version__
    root=args.output.resolve()/f'QuestToolbox-{__version__}'
    if root.exists():
        raise SystemExit('Output directory already exists; choose a fresh output directory.')
    root.mkdir(parents=True)
    runtime=root/'runtime';runtime.mkdir()
    extract(args.python_zip,runtime)
    site=runtime/'Lib/site-packages';site.mkdir(parents=True)
    for wheel in args.wheels.glob('*.whl'):
        extract(wheel,site)
    (runtime/'python312._pth').write_text('python312.zip\n.\n..\nLib/site-packages\nimport site\n','utf-8')
    for path in repo.rglob('*'):
        relative=path.relative_to(repo)
        if any(part in {'.git','__pycache__','.pytest_cache','.venv','build','dist'} for part in relative.parts):
            continue
        if path.is_file():
            dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    shutil.copy2(args.launcher,root/'QuestToolbox.exe')
    (root/'START-HERE.txt').write_text(
        f'QUEST TOOLBOX {__version__} PREVIEW\n\n'
        '1. Extract the entire ZIP. / Распакуйте весь архив.\n'
        '2. Run QuestToolbox.exe. / Запустите QuestToolbox.exe.\n'
        '3. Settings -> Download official ADB, or choose your existing adb.exe.\n'
        '   Настройки -> Скачать официальный ADB или выбрать установленный adb.exe.\n'
        '4. Enable Developer Mode and accept USB debugging inside your Quest.\n'
        '   Включите режим разработчика и разрешите USB-отладку внутри шлема.\n\n'
        'Keep runtime and quest_toolbox folders beside the EXE. Python is included.\n'
        'Не переносите EXE отдельно от папок runtime и quest_toolbox. Python уже включён.\n\n'
        'Preview: physical headset tests are still needed. See README.md.\n'
        'Предварительная версия: требуется проверка на реальном шлеме.\n','utf-8-sig')
    archive=args.output.resolve()/f'QuestToolbox-{__version__}-Windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in root.rglob('*'):
            if path.is_file():z.write(path,root.name+'/'+str(path.relative_to(root)))
    source=args.output.resolve()/f'QuestToolbox-{__version__}-source.zip'
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in repo.rglob('*'):
            if path.is_file() and not any(part in {'.git','__pycache__','.pytest_cache','.venv','build','dist'} for part in path.relative_to(repo).parts):
                z.write(path,'QuestToolbox/'+str(path.relative_to(repo)))
    print(archive,archive.stat().st_size)
    print(source,source.stat().st_size)

if __name__=='__main__':main()
