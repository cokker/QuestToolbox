"""Downloads only from official HTTPS endpoints; archives never escape destination."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request
from urllib.parse import urlparse
import zipfile
from . import __version__
from .core import ToolboxError, Cancelled, data_dir

OFFICIAL_HOSTS = {'dl.google.com', 'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def fetch(url, cancel, progress, limit=250_000_000):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname not in OFFICIAL_HOSTS:
        raise ToolboxError('Неофициальный адрес загрузки отклонён.')
    request = urllib.request.Request(url, headers={'User-Agent': f'QuestToolbox/{__version__}', 'Accept': 'application/vnd.github+json' if 'api.github.com' in url else '*/*'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if urlparse(response.url).scheme != 'https' or urlparse(response.url).hostname not in OFFICIAL_HOSTS:
                raise ToolboxError('Неожиданное перенаправление загрузки.')
            chunks, size = [], 0
            total = response.headers.get('Content-Length', '?')
            while True:
                if cancel.is_set():
                    raise Cancelled('Загрузка отменена.')
                chunk = response.read(256 * 1024)
                if not chunk:
                    return b''.join(chunks)
                size += len(chunk)
                if size > limit:
                    raise ToolboxError('Файл превышает допустимый размер.')
                chunks.append(chunk)
                progress(f'Загружено {size // 1024} КБ / {total} байт')
    except (Cancelled, ToolboxError):
        raise
    except Exception as e:
        raise ToolboxError('Ошибка загрузки. Можно выбрать уже установленный инструмент вручную.\n' + str(e)) from e


def safe_extract(archive: Path, target: Path):
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 800_000_000:
            raise ToolboxError('Распакованный архив слишком большой.')
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            destination = (target / name).resolve()
            if not destination.is_relative_to(target.resolve()) or ':' in name or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ToolboxError('Небезопасный путь в архиве.')
        z.extractall(target)


def install_tool(kind, cancel, progress):
    root = data_dir() / 'tools'
    root.mkdir(exist_ok=True)
    if kind == 'adb':
        platform = 'windows' if os.name == 'nt' else 'linux'
        url = f'https://dl.google.com/android/repository/platform-tools-latest-{platform}.zip'
        exe = 'adb.exe' if os.name == 'nt' else 'adb'
    else:
        if os.name != 'nt':
            raise ToolboxError('Автоматическая установка scrcpy предусмотрена для Windows. На этой ОС выберите установленный файл.')
        metadata = json.loads(fetch('https://api.github.com/repos/Genymobile/scrcpy/releases/latest', cancel, progress, 2_000_000))
        asset = next((a for a in metadata.get('assets', []) if re.fullmatch(r'scrcpy-win64-v[\d.]+\.zip', a['name'])), None)
        if not asset:
            raise ToolboxError('В официальном релизе не найден архив scrcpy для Windows x64.')
        url, exe = asset['browser_download_url'], 'scrcpy.exe'
    with tempfile.TemporaryDirectory(dir=root) as temp:
        temp = Path(temp)
        archive = temp / 'download.zip'
        archive.write_bytes(fetch(url, cancel, progress))
        extracted = temp / 'extracted'
        extracted.mkdir()
        safe_extract(archive, extracted)
        found = list(extracted.rglob(exe))
        if len(found) != 1:
            raise ToolboxError('В архиве не найден однозначный исполняемый файл.')
        source = found[0].parent
        if os.name != 'nt':
            found[0].chmod(0o755)
        destination = root / ('platform-tools' if kind == 'adb' else 'scrcpy')
        backup = root / (destination.name + '.previous')
        if backup.exists():
            raise ToolboxError(f'Найдена резервная копия {backup}. Проверьте её перед обновлением.')
        if destination.exists():
            try:
                destination.rename(backup)
            except OSError as e:
                raise ToolboxError('Не удалось обновить инструмент. Закройте работающие ADB/scrcpy и повторите.\n' + str(e)) from e
        try:
            source.rename(destination)
        except OSError as e:
            if backup.exists():
                try:
                    backup.rename(destination)
                except OSError as restore_error:
                    raise ToolboxError(f'Обновление не удалось. Прежняя версия сохранена в {backup}; восстановите её вручную.\n{restore_error}') from e
                raise ToolboxError('Не удалось обновить инструмент; прежняя версия восстановлена.\n' + str(e)) from e
            raise ToolboxError('Не удалось установить инструмент.\n' + str(e)) from e
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                # Installation succeeded. Preserve the backup for manual cleanup.
                pass
        return str(destination / exe)


def check_update(repository, cancel, progress, include_prereleases=True):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ToolboxError('Укажите репозиторий в формате владелец/название.')
    releases = json.loads(fetch(f'https://api.github.com/repos/{repository}/releases?per_page=30', cancel, progress, 2_000_000))
    if not isinstance(releases, list):
        raise ToolboxError('GitHub вернул неожиданный формат списка релизов.')
    eligible = [r for r in releases if not r.get('draft') and
                (include_prereleases or not r.get('prerelease')) and
                re.fullmatch(r'v?\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', r.get('tag_name', ''))]
    if not eligible:
        raise ToolboxError('В выбранном канале ещё нет опубликованных релизов. Включите предварительные версии или проверьте позже.')
    def order(release):
        numbers = re.match(r'v?(\d+)\.(\d+)\.(\d+)', release['tag_name'])
        return (*map(int, numbers.groups()), not release.get('prerelease'), release.get('published_at') or '')
    info = max(eligible, key=order)
    expected = f'https://github.com/{repository}/releases/'
    if not info.get('html_url', '').lower().startswith(expected.lower()):
        raise ToolboxError('Неожиданный адрес релиза.')
    return info
