"""ADB operations. No host shell, explicit device selection, bounded execution."""
from __future__ import annotations
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable


class ToolboxError(RuntimeError):
    pass


class Cancelled(ToolboxError):
    pass


def data_dir() -> Path:
    p = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'QuestToolbox'
    p.mkdir(parents=True, exist_ok=True)
    return p


def friendly_error(message: str) -> str:
    mapping = {
        'unauthorized': 'Наденьте шлем и разрешите USB-отладку для этого компьютера.',
        'offline': 'Шлем не отвечает. Разбудите его и переподключите кабель или Wi-Fi.',
        'no devices': 'Шлем не найден. Проверьте кабель, режим разработчика и драйвер ADB.',
        'device not found': 'Соединение со шлемом потеряно. Подключите его заново.',
        'INSTALL_FAILED_UPDATE_INCOMPATIBLE': 'Подпись APK отличается от установленного приложения. Автоматическое удаление отключено: оно уничтожило бы данные.',
        'INSTALL_FAILED_VERSION_DOWNGRADE': 'APK старее установленной версии. Выберите более новую сборку.',
        'INSTALL_FAILED_INSUFFICIENT_STORAGE': 'На шлеме недостаточно свободного места.',
        'INSTALL_FAILED_NO_MATCHING_ABIS': 'Этот APK собран для несовместимого процессора.',
        'INSTALL_FAILED_MISSING_SPLIT': 'Нужны все части приложения. Используйте установку набора split APK.',
        'Permission denied': 'Прошивка запрещает эту операцию через ADB.',
        'more than one device': 'Выберите конкретный шлем в верхней панели.',
    }
    for token, explanation in mapping.items():
        if token.lower() in message.lower():
            return explanation + '\n\n' + message[-3000:]
    return message[-5000:]


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str


def parse_devices(raw: str) -> list[Device]:
    result = []
    for line in raw.splitlines():
        bits = line.strip().split()
        if len(bits) < 2 or bits[0] == 'List' or bits[0].startswith('*'):
            continue
        state = bits[1]
        if state not in ('device', 'offline', 'unauthorized', 'recovery', 'sideload', 'no'):
            continue
        model = next((x[6:] for x in bits if x.startswith('model:')), '')
        result.append(Device(bits[0], state, model.replace('_', ' ')))
    return result


def parse_props(raw: str) -> dict[str, str]:
    return dict(re.findall(r'^\[([^\]]+)\]: \[(.*)\]$', raw, re.M))


# Values are from Meta's system-property documentation, retrieved 2026-10-01.
# This is an allow-list, not a claim of hardware verification.
RATES = {'Quest': (60, 72), 'Quest 2': (60, 72, 80, 90, 120),
         'Quest Pro': (72, 80, 90), 'Quest 3': (72, 80, 90, 120),
         'Quest 3S': (72, 80, 90, 120)}


def identify_model(props: dict[str, str]) -> str | None:
    model = props.get('ro.product.model', '').replace('_', ' ').lower()
    model = re.sub(r'^(meta|oculus)\s+', '', model).strip()
    for canonical in RATES:
        if model.replace(' ', '') == canonical.lower().replace(' ', ''):
            return canonical
    return None


def endpoint(value: str) -> str:
    value = value.strip()
    host, sep, port = value.partition(':')
    try:
        addr = ipaddress.IPv4Address(host)
        number = int(port) if sep else 5555
    except (ValueError, ipaddress.AddressValueError):
        raise ToolboxError('Введите IPv4-адрес шлема, например 192.168.1.25:5555.') from None
    if not (1 <= number <= 65535) or addr.is_unspecified or addr.is_multicast:
        raise ToolboxError('Недопустимый адрес или порт.')
    return f'{addr}:{number}'


def remote_path(value: str) -> str:
    if '\x00' in value or '\n' in value or '\r' in value:
        raise ToolboxError('Недопустимое имя файла.')
    path = PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ToolboxError('Нужен абсолютный путь без переходов «..».')
    if str(path) != '/sdcard' and not str(path).startswith('/sdcard/'):
        raise ToolboxError('Файловый менеджер работает внутри /sdcard.')
    return str(path)


def package_name(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', value):
        raise ToolboxError('Недопустимое имя пакета.')
    return value


def redact(text: str, serials: tuple[str, ...] = ()) -> str:
    for serial in serials:
        if serial:
            text = text.replace(serial, '<device>')
    text = re.sub(r'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b', '<mac>', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '<ip>', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '<email>', text)
    text = re.sub(r'(?i)(authorization\s*[:=]\s*|bearer\s+|(?:access_token|refresh_token|password|token)\s*[:=]\s*)[^\s,;]+', r'\1<hidden>', text)
    text = re.sub(r'(?i)C:\\Users\\[^\\\s]+', r'C:\\Users\\<user>', text)
    return text


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / 'settings.json'
        try:
            self.values = json.loads(self.path.read_text('utf-8'))
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), 'utf-8')
        tmp.replace(self.path)


class Adb:
    def __init__(self, executable: str, serial: str = '', cancel: threading.Event | None = None,
                 progress: Callable[[str], None] | None = None):
        self.executable = executable
        self.serial = serial
        self.cancel = cancel or threading.Event()
        self.progress = progress or (lambda _: None)

    def command(self, args: list[str], timeout: float = 30, device: bool = True,
                binary: bool = False, honor_cancel: bool = True):
        if device and not self.serial:
            raise ToolboxError('Сначала выберите подключённый шлем.')
        if honor_cancel and self.cancel.is_set():
            raise Cancelled('Операция отменена. Уже завершённые действия не отменяются.')
        cmd = [self.executable] + (['-s', self.serial] if device else []) + args
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as e:
            raise ToolboxError('Не удалось запустить ADB. Откройте раздел «Настройки» и выберите adb.exe.\n' + str(e)) from e
        start = time.monotonic()
        while True:
            try:
                out, err = p.communicate(timeout=.15)
                break
            except subprocess.TimeoutExpired:
                if (honor_cancel and self.cancel.is_set()) or time.monotonic() - start > timeout:
                    p.kill()
                    p.communicate()
                    if honor_cancel and self.cancel.is_set():
                        raise Cancelled('Операция отменена. Состояние шлема могло измениться; обновите данные.')
                    raise ToolboxError('Время ожидания истекло. Проверьте подключение; операция могла выполниться частично.')
        detail = (out + err).decode('utf-8', errors='replace').strip()
        if p.returncode or re.search(r'(^|\n)(Failure\s*\[|adb: error:|error:|failed to |cannot connect|unable to connect)', detail, re.I):
            raise ToolboxError(friendly_error(detail or f'ADB завершился с кодом {p.returncode}'))
        return out if binary else detail

    def shell(self, *args: str, timeout: float = 30, honor_cancel: bool = True) -> str:
        # adb shell joins its arguments before the Android shell parses them.
        # Quote for that remote shell as well as avoiding a host shell entirely.
        return self.command(['shell', shlex.join(args)], timeout, honor_cancel=honor_cancel)

    def devices(self) -> list[Device]:
        return parse_devices(self.command(['devices', '-l'], device=False))

    def getprop(self, name: str) -> str:
        return self.shell('getprop', name).strip()

    def snapshot(self) -> dict:
        props = parse_props(self.shell('getprop'))
        data = {'props': props, 'model': identify_model(props), 'warnings': []}
        for key, cmd in {'battery': ('dumpsys', 'battery'), 'disk': ('df', '-k', '/sdcard'),
                         'ip': ('ip', '-o', '-4', 'addr', 'show', 'wlan0')}.items():
            try:
                data[key] = self.shell(*cmd)
            except Cancelled:
                raise
            except ToolboxError as e:
                data[key] = ''
                data['warnings'].append(f'{key}: {e}')
        return data

    def list_apps(self, system: bool = False) -> list[str]:
        raw = self.shell('pm', 'list', 'packages', *([] if system else ['-3']))
        return sorted(line[8:].strip() for line in raw.splitlines() if line.startswith('package:'))

    def install(self, paths: list[str], split: bool = False) -> str:
        if not paths:
            raise ToolboxError('Выберите APK.')
        for path in paths:
            if not Path(path).is_file() or Path(path).suffix.lower() != '.apk':
                raise ToolboxError('Поддерживаются файлы .apk; для APKM/XAPK сначала распакуйте контейнер.')
        if split:
            result = self.command(['install-multiple', '-r', *paths], timeout=900)
            if 'Success' not in result:
                raise ToolboxError('Установка не подтверждена:\n' + result)
            return result
        for index, path in enumerate(paths, 1):
            self.progress(f'{index}/{len(paths)} · {Path(path).name}')
            result = self.command(['install', '-r', path], timeout=900)
            if 'Success' not in result:
                raise ToolboxError('Установка не подтверждена:\n' + result)
        return f'Установлено APK: {len(paths)}'

    def launch(self, package: str) -> str:
        package = package_name(package)
        resolved = self.shell('cmd', 'package', 'resolve-activity', '--brief', package)
        component = next((x.strip() for x in reversed(resolved.splitlines()) if re.fullmatch(r'[\w.]+/[\w.$]+', x.strip())), None)
        if not component:
            raise ToolboxError('У приложения нет доступной стартовой Activity.')
        result = self.shell('am', 'start', '-n', component)
        if 'Error' in result or 'Exception' in result:
            raise ToolboxError(result)
        return result

    def export_apk(self, package: str, destination: str) -> str:
        package = package_name(package)
        target = Path(destination) / package
        target.mkdir(parents=True, exist_ok=True)
        paths = [line[8:].strip() for line in self.shell('pm', 'path', package).splitlines() if line.startswith('package:')]
        if not paths:
            raise ToolboxError('APK не найден.')
        for index, path in enumerate(paths, 1):
            self.progress(f'APK {index}/{len(paths)}')
            self.command(['pull', path, str(target / PurePosixPath(path).name)], timeout=600)
        return f'Сохранено {len(paths)} APK в {target}. Личные данные приложения не копируются.'

    def list_files(self, folder: str) -> list[tuple[str, bool]]:
        folder = remote_path(folder)
        # NUL-delimited entries preserve whitespace, tabs and Unicode.
        script = 'for f in "$1"/.[!.]* "$1"/..?* "$1"/*; do [ -e "$f" ] || continue; if [ -d "$f" ]; then printf "d\\000%s\\000" "${f##*/}"; else printf "f\\000%s\\000" "${f##*/}"; fi; done'
        # Verify directory readability first, rather than displaying an empty list on denial.
        self.shell('sh', '-c', 'test -d "$1" && test -r "$1" && test -x "$1" && ls -A "$1" >/dev/null', 'qtb', folder)
        raw = self.shell('sh', '-c', script, 'qtb', folder)
        chunks = raw.rstrip('\x00').split('\x00') if raw else []
        return sorted([(chunks[i + 1], chunks[i] == 'd') for i in range(0, len(chunks) - 1, 2)], key=lambda x: (not x[1], x[0].lower()))

    def push_files(self, paths: list[str], destination: str) -> str:
        destination = remote_path(destination)
        for index, path in enumerate(paths, 1):
            self.progress(f'{index}/{len(paths)} · {Path(path).name}')
            self.command(['push', path, destination + '/'], timeout=1800)
        return f'Передано файлов: {len(paths)}'

    def apply_properties(self, changes: dict[str, str], model: str) -> dict[str, str]:
        validate_properties(changes, model)
        previous = {key: self.getprop(key) for key in changes}
        touched = []
        try:
            for key, value in changes.items():
                touched.append(key)
                self.shell('setprop', key, value)
                if self.getprop(key) != value:
                    raise ToolboxError(f'Прошивка не подтвердила значение {key}.')
        except Exception as original:
            errors = []
            for key in reversed(touched):
                try:
                    self.shell('setprop', key, previous[key], honor_cancel=False)
                    actual = self.shell('getprop', key, honor_cancel=False).strip()
                    if actual != previous[key]:
                        errors.append(key)
                except ToolboxError:
                    errors.append(key)
            suffix = '\nИсходные свойства восстановлены.' if not errors else '\nОткат не подтверждён: ' + ', '.join(errors) + '. Перезагрузите шлем для сброса временных свойств.'
            raise ToolboxError(str(original) + suffix) from original
        return previous

    def restore_properties(self, previous: dict[str, str]) -> str:
        failures = []
        for key, value in previous.items():
            if key not in PROPERTY_KEYS or not re.fullmatch(r'\d*', value):
                raise ToolboxError('Недопустимые данные восстановления.')
            try:
                self.shell('setprop', key, value)
                if self.getprop(key) != value:
                    failures.append(key)
            except ToolboxError:
                failures.append(key)
        if failures:
            raise ToolboxError('Не восстановлено: ' + ', '.join(failures) + '. Перезагрузка сбросит временные свойства.')
        return 'Исходные свойства восстановлены. Изменение картинки зависит от приложения.'

    def screenshot(self, destination: str) -> str:
        raw = self.command(['exec-out', 'screencap', '-p'], timeout=45, binary=True)
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ToolboxError('Прошивка не вернула PNG. Используйте запись/трансляцию или штатный захват шлема.')
        Path(destination).write_bytes(raw)
        return 'Скриншот сохранён: ' + destination

    def diagnostics(self) -> str:
        snap = self.snapshot()
        safe_props = {k: v for k, v in snap['props'].items() if k in (
            'ro.product.model', 'ro.product.manufacturer', 'ro.build.version.release',
            'ro.build.version.sdk', 'ro.build.version.incremental', 'ro.product.cpu.abi') or k.startswith('debug.oculus.')}
        sections = ['Quest Toolbox diagnostics', json.dumps(safe_props, ensure_ascii=False, indent=2), snap['battery'], snap['disk']]
        for cmd in [('id',), ('dumpsys', 'thermalservice'), ('dumpsys', 'display'), ('logcat', '-d', '-t', '300', '-v', 'threadtime')]:
            try:
                sections.append('$ ' + ' '.join(cmd) + '\n' + self.shell(*cmd, timeout=40))
            except Cancelled:
                raise
            except ToolboxError as e:
                sections.append(str(e))
        serials = tuple(v for k, v in snap['props'].items() if 'serial' in k) + (self.serial,)
        return redact('\n\n'.join(sections), serials)


PROPERTY_KEYS = {'debug.oculus.refreshRate', 'debug.oculus.textureWidth', 'debug.oculus.textureHeight',
                 'debug.oculus.foveation.dynamic', 'debug.oculus.fullRateCapture',
                 'debug.oculus.capture.width', 'debug.oculus.capture.height', 'debug.oculus.capture.bitrate'}


def validate_properties(changes: dict[str, str], model: str):
    if model not in RATES:
        raise ToolboxError('Для этой модели нет проверенного списка параметров. Доступны общие функции ADB.')
    for key, value in changes.items():
        if key not in PROPERTY_KEYS or not re.fullmatch(r'\d+', value):
            raise ToolboxError('Недопустимое свойство или значение.')
        n = int(value)
        if key.endswith('refreshRate') and n not in RATES[model]:
            raise ToolboxError(f'{n} Гц не входят в документированные режимы {model}.')
        if key.endswith(('textureWidth', 'textureHeight', 'capture.width', 'capture.height')) and not (512 <= n <= 4096 and n % 2 == 0):
            raise ToolboxError('Размер должен быть чётным числом от 512 до 4096.')
        if key.endswith(('foveation.dynamic', 'fullRateCapture')) and n not in (0, 1):
            raise ToolboxError('Значение должно быть 0 или 1.')
        if key.endswith('capture.bitrate') and not 1_000_000 <= n <= 40_000_000:
            raise ToolboxError('Битрейт должен быть от 1 до 40 Мбит/с.')


def find_adb(configured: str = '') -> str:
    candidates = [configured, str(data_dir() / 'tools/platform-tools/adb.exe'),
                  str(data_dir() / 'tools/platform-tools/adb'), shutil.which('adb') or '']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return configured or ('adb.exe' if os.name == 'nt' else 'adb')
