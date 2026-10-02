from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import threading
import time
from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool, QTimer, QProcess, QProcessEnvironment, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QColor, QPen, QLinearGradient, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QListWidget, QStackedWidget, QScrollArea, QComboBox, QLineEdit,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QInputDialog,
    QCheckBox, QSpinBox, QProgressBar, QDialog, QDialogButtonBox, QAbstractItemView)
from . import __version__
from .core import (Adb, Device, ToolboxError, Cancelled, Settings, RATES, data_dir, find_adb,
                   endpoint, remote_path, package_name, redact, identify_model)
from .downloads import install_tool, check_update
from .style import stylesheet


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.signals = Signals()
        self.function = function

    def run(self):
        try:
            self.signals.done.emit(self.function(self.signals.progress.emit))
        except Exception as e:
            self.signals.failed.emit(str(e))


class HeadsetArt(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 120)
        self.setMaximumWidth(270)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width()/2, self.height()/2)
        p.scale(min(self.width()/260, self.height()/140), min(self.width()/260, self.height()/140))
        p.setPen(QPen(QColor('#476a83'), 7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(-93, -45, 186, 87, 35, 35)
        g = QLinearGradient(-100, -40, 100, 50)
        g.setColorAt(0, QColor('#c9e9f3'))
        g.setColorAt(1, QColor('#759bb8'))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(-107, -33, 214, 88, 34, 34)
        p.setBrush(QColor('#152235'))
        for x in (-64, -7, 50):
            p.drawRoundedRect(x, -11, 14, 42, 7, 7)
        p.setBrush(QColor('#ffab6b'))
        p.drawEllipse(83, 7, 7, 7)


class Window(QMainWindow):
    def __init__(self, settings=None, auto_scan=True):
        super().__init__()
        self.settings = settings or Settings()
        self.lang = self.settings.values.get('language', 'ru')
        self.light = self.settings.values.get('light', False)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self.cancel = threading.Event()
        self.devices = []
        self.snapshot = None
        self.snapshot_serial = ''
        self.history = list(self.settings.values.get('history', []))[-300:]
        self.previous = {}
        self.log_process = None
        self.mirror_process = None
        self.report = ''
        self.setWindowTitle(f'Quest Toolbox · {__version__}')
        self.resize(1220, 840)
        self.setMinimumSize(940, 660)
        self.setAcceptDrops(True)
        self.build()
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.poll)
        if auto_scan:
            self.timer.start()
            QTimer.singleShot(100, self.poll)

    def t(self, ru, en):
        return en if self.lang == 'en' else ru

    def label(self, text, role=None):
        w = QLabel(text)
        w.setWordWrap(True)
        if role:
            w.setObjectName(role)
        return w

    def button(self, text, action, primary=False, danger=False):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setProperty('primary', primary)
        b.setProperty('danger', danger)
        b.clicked.connect(lambda checked=False: self.guard(action))
        return b

    def guard(self, action):
        try:
            action()
        except Exception as e:
            self.error(str(e))

    def row(self, *widgets):
        row = QHBoxLayout()
        row.setSpacing(10)
        for w in widgets:
            row.addWidget(w)
        return row

    def card(self):
        w = QFrame()
        w.setObjectName('card')
        layout = QVBoxLayout(w)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        return w, layout

    def page(self, title, subtitle):
        area = QScrollArea()
        area.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 3, 6, 15)
        layout.setSpacing(17)
        layout.addWidget(self.label(title, 'title'))
        layout.addWidget(self.label(subtitle, 'muted'))
        area.setWidget(page)
        self.stack.addWidget(area)
        return layout

    def build(self):
        QApplication.instance().setStyleSheet(stylesheet(self.light))
        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(22)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(215)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 24, 16, 18)
        side.addWidget(self.label('QUEST\nTOOLBOX', 'brand'))
        side.addWidget(self.label('by COKKER  /  '+__version__, 'muted'))
        side.addSpacing(25)
        self.nav = QListWidget()
        self.nav.addItems([self.t('Обзор','Overview'), self.t('Подключение','Connection'), self.t('Приложения','Apps'),
                           self.t('Файлы','Files'), self.t('Дисплей','Display'), self.t('Захват экрана','Screen capture'),
                           self.t('Диагностика','Diagnostics'), self.t('История','History'), self.t('Настройки','Settings')])
        side.addWidget(self.nav, 1)
        side.addWidget(self.label(self.t('Твой Quest.\nВсё под рукой.','Your Quest.\nEverything in reach.'), 'muted'))
        outer.addWidget(sidebar)
        right = QVBoxLayout()
        self.selector = QComboBox()
        self.selector.setMinimumWidth(350)
        self.selector.addItem(self.t('Шлем не выбран','No headset selected'), None)
        self.selector.currentIndexChanged.connect(self.selected)
        self.refresh_button = self.button(self.t('Обновить','Refresh'), self.scan)
        self.connection_badge = self.label('USB / Wi-Fi', 'muted')
        right.addLayout(self.row(self.selector, self.refresh_button, self.connection_badge))
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.home_page()
        self.connection_page()
        self.apps_page()
        self.files_page()
        self.display_page()
        self.capture_page()
        self.diagnostics_page()
        self.history_page()
        self.settings_page()
        self.status = self.label(self.t('Готов к подключению','Ready to connect'), 'muted')
        self.status.setMaximumHeight(58)
        self.progressbar = QProgressBar()
        self.progressbar.setRange(0, 1)
        self.progressbar.setTextVisible(False)
        self.progressbar.setFixedHeight(6)
        self.cancel_button = self.button(self.t('Отмена','Cancel'), self.cancel.set)
        self.cancel_button.hide()
        right.addLayout(self.row(self.status, self.cancel_button))
        right.addWidget(self.progressbar)
        outer.addLayout(right, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.refresh_history()
        self.update_display()
        self.setWindowIcon(self.make_icon())

    def make_icon(self):
        pix = QPixmap(64,64)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor('#ff9b54'))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2,2,60,60,16,16)
        p.setBrush(QColor('#152235'))
        p.drawRoundedRect(10,20,44,26,9,9)
        p.setBrush(QColor('#b8e4ee'))
        p.drawEllipse(18,27,10,10)
        p.drawEllipse(36,27,10,10)
        p.end()
        return QIcon(pix)

    def home_page(self):
        layout = self.page(self.t('Твой Quest, без лишних команд','Your Quest, without the commands'),
                           self.t('Подключение, приложения и файлы — в одном окне.','Connection, apps and files — in one place.'))
        card, box = self.card()
        hero = QHBoxLayout()
        words = QVBoxLayout()
        words.addWidget(self.label('QUEST  /  CONTROL CENTER', 'eyebrow'))
        self.model_label = self.label(self.t('Подключи свой шлем','Connect your headset'), 'hero')
        words.addWidget(self.model_label)
        self.model_detail = self.label(self.t('Quest • Quest 2 • Quest Pro • Quest 3 • Quest 3S','Quest • Quest 2 • Quest Pro • Quest 3 • Quest 3S'), 'muted')
        words.addWidget(self.model_detail)
        hero.addLayout(words, 1)
        hero.addWidget(HeadsetArt())
        box.addLayout(hero)
        box.addLayout(self.row(self.button(self.t('Подключить','Connect'), lambda:self.nav.setCurrentRow(1), True),
                               self.button(self.t('Обновить состояние','Refresh status'), self.read_snapshot)))
        layout.addWidget(card)
        stats = QHBoxLayout()
        self.stats = {}
        for key, title in [('battery',self.t('ЗАРЯД','BATTERY')),('storage',self.t('СВОБОДНО','FREE SPACE')),('ip',self.t('IP-АДРЕС','IP ADDRESS'))]:
            card, box = self.card()
            box.addWidget(self.label(title, 'eyebrow'))
            self.stats[key] = self.label('—','stat')
            box.addWidget(self.stats[key])
            stats.addWidget(card)
        layout.addLayout(stats)
        card, box = self.card()
        box.addWidget(self.label(self.t('Быстрые действия','Quick actions')))
        box.addLayout(self.row(self.button(self.t('Установить APK','Install APK'), self.choose_apk, True),
                               self.button(self.t('Открыть файлы','Open files'), lambda:self.nav.setCurrentRow(3)),
                               self.button(self.t('Трансляция','Mirror screen'), self.start_mirror)))
        box.addLayout(self.row(self.button(self.t('Разбудить экран','Wake screen'), lambda:self.device_command(['shell','input keyevent KEYCODE_WAKEUP'])),
                               self.button(self.t('Перезапустить шлем','Reboot headset'), self.reboot)))
        self.favorites = QComboBox()
        self.refresh_favorites()
        box.addLayout(self.row(self.favorites, self.button(self.t('Запустить избранное','Launch favorite'), self.launch_favorite)))
        box.addWidget(self.label(self.t('Для первого подключения нужны режим разработчика и разрешение USB-отладки внутри шлема.','First connection requires Developer Mode and accepting USB debugging inside the headset.'),'muted'))
        layout.addWidget(card)
        layout.addStretch()

    def connection_page(self):
        layout = self.page(self.t('Подключение','Connection'),self.t('Один компьютер, несколько шлемов. Всегда проверяй выбранное устройство.','One computer, multiple headsets. Always check the selected device.'))
        card, box = self.card()
        box.addWidget(self.label(self.t('Первое подключение по USB','First USB connection')))
        box.addWidget(self.label(self.t('1. Включи режим разработчика для шлема в приложении Meta Horizon.\n2. Подключи USB-кабель с передачей данных и разбуди шлем.\n3. Внутри шлема разреши USB-отладку для этого ПК.\n4. Нажми «Обновить» и выбери свой Quest сверху.','1. Enable Developer Mode for the headset in Meta Horizon.\n2. Connect a USB data cable and wake the headset.\n3. Accept USB debugging inside the headset.\n4. Refresh and choose the headset above.')))
        box.addLayout(self.row(self.button(self.t('Инструкция Meta','Meta setup guide'),lambda:self.open_url('https://developers.meta.com/horizon/documentation/native/android/mobile-device-setup/')),
                               self.button(self.t('Установить / выбрать ADB','Install / select ADB'),lambda:self.nav.setCurrentRow(8))))
        layout.addWidget(card)
        card, box = self.card()
        box.addWidget(self.label(self.t('Подключение по Wi-Fi','Connect over Wi-Fi')))
        self.address = QLineEdit(self.settings.values.get('endpoint',''))
        self.address.setPlaceholderText('192.168.1.25:5555')
        box.addWidget(self.address)
        box.addLayout(self.row(self.button(self.t('Включить Wi-Fi ADB через USB','Enable Wi-Fi ADB via USB'),self.enable_wifi,True),
                               self.button(self.t('Подключиться','Connect'), self.connect_wifi)))
        box.addLayout(self.row(self.button(self.t('Отключить соединение','Disconnect session'), self.disconnect_wifi),
                               self.button(self.t('Отключить Wi-Fi ADB на шлеме','Disable Wi-Fi ADB on headset'), self.disable_wifi)))
        box.addWidget(self.label(self.t('ПК и шлем должны быть в одной доверенной сети. Отключение соединения не выключает Wi-Fi ADB на шлеме. После перезагрузки может снова понадобиться USB.','Use the same trusted network. Disconnecting the session does not disable Wi-Fi ADB on the headset. USB setup may be needed again after a reboot.'),'muted'))
        layout.addWidget(card)
        card, box = self.card()
        box.addWidget(self.label(self.t('Имя выбранного шлема','Selected headset nickname')))
        box.addWidget(self.button(self.t('Переименовать в Toolbox','Set nickname in Toolbox'),self.rename_device))
        box.addWidget(self.button(self.t('Перезапустить сервер ADB','Restart ADB server'),self.restart_adb))
        layout.addWidget(card)
        layout.addStretch()

    def apps_page(self):
        layout = self.page(self.t('Приложения','Apps'),self.t('Перетащи APK в окно. Установленные данные сохраняются при совместимом обновлении.','Drop APK files here. Compatible updates preserve installed app data.'))
        layout.addLayout(self.row(self.button(self.t('Установить APK','Install APK'),self.choose_apk,True),
                                  self.button(self.t('Набор split APK','Split APK set'),lambda:self.choose_apk(True)),
                                  self.button(self.t('Загрузить список','Load apps'),self.load_apps)))
        self.app_filter = QLineEdit()
        self.app_filter.setPlaceholderText(self.t('Поиск по имени пакета…','Search package names…'))
        self.app_filter.textChanged.connect(self.filter_apps)
        self.system_apps = QCheckBox(self.t('Показывать системные приложения','Show system apps'))
        self.system_apps.toggled.connect(self.system_apps_changed)
        layout.addLayout(self.row(self.app_filter,self.system_apps))
        self.app_table = QTableWidget(0,1)
        self.app_table.setHorizontalHeaderLabels([self.t('Пакет приложения','Application package')])
        self.table_setup(self.app_table)
        self.app_table.setMinimumHeight(300)
        layout.addWidget(self.app_table)
        layout.addLayout(self.row(self.button(self.t('Запустить','Launch'),self.launch_app),
                                  self.button(self.t('Остановить','Force stop'),self.stop_app),
                                  self.button(self.t('Сведения','Details'),self.app_details),
                                  self.button(self.t('Экспорт APK','Export APK'),self.export_apk)))
        layout.addWidget(self.button(self.t('Добавить / убрать из избранного','Toggle favorite'),self.toggle_favorite))
        layout.addWidget(self.button(self.t('Удалить выбранное приложение','Uninstall selected app'),self.uninstall_app,danger=True))
        layout.addWidget(self.label(self.t('Экспорт APK не является резервной копией сохранений. Удаление системных пакетов здесь отключено.','APK export does not back up game saves. System package removal is disabled here.'),'muted'))

    def files_page(self):
        layout = self.page(self.t('Файлы и записи','Files & recordings'),self.t('Общее хранилище шлема. Доступ к Android/data зависит от прошивки.','Shared headset storage. Android/data access depends on firmware.'))
        self.folder = QLineEdit('/sdcard/Download')
        self.folder.returnPressed.connect(lambda:self.guard(self.load_files))
        layout.addLayout(self.row(self.button('↑', self.parent_folder),self.folder,self.button(self.t('Открыть','Open'),self.load_files)))
        layout.addLayout(self.row(self.button('Download',lambda:self.open_folder('/sdcard/Download')),
                                  self.button(self.t('Видео','Videos'),lambda:self.open_folder('/sdcard/Oculus/VideoShots')),
                                  self.button(self.t('Фото','Photos'),lambda:self.open_folder('/sdcard/Oculus/Screenshots'))))
        self.file_table = QTableWidget(0,2)
        self.file_table.setHorizontalHeaderLabels([self.t('Имя','Name'),self.t('Тип','Type')])
        self.table_setup(self.file_table)
        self.file_table.setMinimumHeight(280)
        self.file_table.cellDoubleClicked.connect(self.enter_file)
        layout.addWidget(self.file_table)
        layout.addLayout(self.row(self.button(self.t('Отправить файлы','Upload files'),self.upload_files,True),
                                  self.button(self.t('Скачать выбранное','Download selection'),self.download_file),
                                  self.button(self.t('Создать папку','New folder'),self.new_folder)))
        layout.addWidget(self.button(self.t('Удалить выбранный файл / папку','Delete selected file / folder'),self.delete_file,danger=True))
        layout.addWidget(self.label(self.t('Перезапись и удаление требуют подтверждения. Уже переданные файлы не удаляются при отмене очереди.','Overwrites and deletion require confirmation. Cancelling a queue does not remove files already transferred.'),'muted'))

    def display_page(self):
        layout = self.page(self.t('Дисплей и рендеринг','Display & rendering'),self.t('Документированные временные параметры Meta. Приложение и прошивка могут их переопределять.','Documented temporary Meta properties. Apps and firmware may override them.'))
        card, box = self.card()
        self.display_note = self.label('','muted')
        box.addWidget(self.display_note)
        self.refresh_rate = QComboBox()
        self.texture_w, self.texture_h = QSpinBox(), QSpinBox()
        for spin, value in [(self.texture_w,1440),(self.texture_h,1584)]:
            spin.setRange(512,4096)
            spin.setSingleStep(2)
            spin.setValue(value)
        self.use_texture = QCheckBox(self.t('Изменить размер текстуры рендеринга','Override render texture size'))
        box.addWidget(self.label(self.t('Частота дисплея','Display refresh rate')))
        box.addWidget(self.refresh_rate)
        box.addWidget(self.use_texture)
        box.addLayout(self.row(self.texture_w,self.texture_h))
        self.dynamic_ffr = QComboBox()
        self.dynamic_ffr.addItems([self.t('Динамическая фовеация: не менять','Dynamic foveation: unchanged'),self.t('Выключить','Disable'),self.t('Включить','Enable')])
        box.addWidget(self.dynamic_ffr)
        self.apply_display_button = self.button(self.t('Применить и проверить свойства','Apply & verify properties'),self.apply_display,True)
        box.addWidget(self.apply_display_button)
        box.addLayout(self.row(self.button(self.t('Вернуть исходные значения','Restore original values'),self.restore_display),
                               self.button(self.t('Считать текущие свойства','Read current properties'),self.read_display)))
        box.addWidget(self.label(self.t('Проверка подтверждает сохранение свойства, а не фактический FPS. Параметры сбрасываются после перезагрузки. Настройки текстур относятся к автономным приложениям, не к разрешению Steam Link / PCVR.','Verification confirms the stored property, not actual FPS. Properties reset after reboot. Texture settings target standalone apps, not Steam Link / PCVR resolution.'),'muted'))
        layout.addWidget(card)
        card, box = self.card()
        box.addWidget(self.label(self.t('Профили для этой модели','Profiles for this model')))
        self.profiles = QComboBox()
        box.addWidget(self.profiles)
        box.addLayout(self.row(self.button(self.t('Сохранить профиль','Save profile'),self.save_profile),
                               self.button(self.t('Загрузить в форму','Load into form'),self.load_profile),
                               self.button(self.t('Удалить профиль','Delete profile'),self.delete_profile)))
        layout.addWidget(card)
        layout.addStretch()

    def capture_page(self):
        layout = self.page(self.t('Захват экрана','Screen capture'),self.t('Трансляция и запись через scrcpy, снимки через ADB.','Mirror and record using scrcpy; take screenshots through ADB.'))
        card, box = self.card()
        self.capture_size = QComboBox()
        self.capture_size.addItems(['1024','1600','1920'])
        self.capture_size.setCurrentText('1600')
        box.addWidget(self.label(self.t('Максимальная сторона видео','Maximum video dimension')))
        box.addWidget(self.capture_size)
        self.capture_audio = QCheckBox(self.t('Звук (зависит от прошивки и приложения)','Audio (depends on firmware and app)'))
        box.addWidget(self.capture_audio)
        box.addLayout(self.row(self.button(self.t('Открыть трансляцию','Start mirroring'),self.start_mirror,True),
                               self.button(self.t('Записать в MP4 на ПК','Record MP4 on PC'),lambda:self.start_mirror(True)),
                               self.button(self.t('Остановить','Stop'),self.stop_mirror)))
        box.addWidget(self.button(self.t('Сохранить скриншот PNG','Save PNG screenshot'),self.screenshot))
        box.addWidget(self.label(self.t('Вид может содержать оба глаза или системную поверхность. Защищённый контент, passthrough и VR-ввод могут быть недоступны. Обычная трансляция запускается без удалённого управления.','The image may show both eyes or a system surface. Protected content, passthrough and VR input may be unavailable. Mirroring runs without remote control.'),'muted'))
        layout.addWidget(card)
        card, box = self.card()
        box.addWidget(self.label(self.t('Параметры штатной записи Quest','Quest native recording settings')))
        self.video_w, self.video_h, self.video_bitrate = QSpinBox(), QSpinBox(), QSpinBox()
        for spin in (self.video_w,self.video_h):
            spin.setRange(512,4096)
            spin.setSingleStep(2)
            spin.setValue(1024)
        self.video_bitrate.setRange(1,40)
        self.video_bitrate.setValue(5)
        self.video_bitrate.setSuffix(' Mbps')
        box.addLayout(self.row(self.video_w,self.video_h,self.video_bitrate))
        self.full_capture = QCheckBox(self.t('Записывать с полной частотой дисплея','Capture at full display refresh rate'))
        box.addWidget(self.full_capture)
        box.addWidget(self.button(self.t('Применить параметры записи','Apply recording properties'),self.apply_capture))
        box.addWidget(self.label(self.t('Эти параметры не меняют scrcpy. Штатную запись запускай и останавливай в меню шлема.','These settings do not affect scrcpy. Start and stop native recording from the headset menu.'),'muted'))
        layout.addWidget(card)
        self.mirror_status = self.label(self.t('Трансляция не запущена','Mirroring is not running'),'muted')
        layout.addWidget(self.mirror_status)
        layout.addStretch()

    def diagnostics_page(self):
        layout = self.page(self.t('Диагностика','Diagnostics'),self.t('Живой logcat, фильтры и отчёт с предварительным просмотром.','Live logcat, filters and a report preview.'))
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText(self.t('Фильтр по тексту или имени пакета…','Filter text or package name…'))
        self.log_level = QComboBox()
        self.log_level.addItems(['V','D','I','W','E','F'])
        self.log_level.setCurrentText('I')
        layout.addLayout(self.row(self.log_filter,self.log_level,self.button(self.t('Старт','Start'),self.start_log),self.button(self.t('Стоп','Stop'),self.stop_log)))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setMinimumHeight(250)
        layout.addWidget(self.log_view)
        layout.addLayout(self.row(self.button(self.t('Сохранить видимые логи','Save visible logs'),self.save_logs),
                                  self.button(self.t('Очистить окно','Clear view'),self.log_view.clear),
                                  self.button(self.t('Собрать отчёт','Build report'),self.build_report,True)))
        layout.addWidget(self.label(self.t('Перед отправкой проверь отчёт: автоматическое скрытие IP, серийных номеров и токенов не гарантирует удаление всех личных данных. Отчёты никуда не отправляются автоматически.','Review reports before sharing: automatic redaction may not catch every private value. Reports are never uploaded automatically.'),'muted'))

    def history_page(self):
        layout = self.page(self.t('История действий','Activity history'),self.t('Последние 300 операций. Хранится только на этом компьютере.','Last 300 operations, stored only on this computer.'))
        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        layout.addWidget(self.history_view,1)
        layout.addWidget(self.button(self.t('Очистить историю','Clear history'),self.clear_history))

    def settings_page(self):
        layout = self.page(self.t('Настройки Toolbox','Toolbox settings'),self.t('Windows 10/11 x64 · без обязательной установки Python','Windows 10/11 x64 · no separate Python install required'))
        card, box = self.card()
        self.adb_path = QLineEdit(self.settings.values.get('adb',''))
        self.adb_path.setPlaceholderText(self.t('Автопоиск ADB или полный путь к adb.exe','Auto-detect ADB or path to adb.exe'))
        box.addWidget(self.label('Android SDK Platform-Tools / ADB'))
        box.addWidget(self.adb_path)
        box.addLayout(self.row(self.button(self.t('Выбрать adb.exe','Choose adb.exe'),lambda:self.choose_tool('adb')),
                               self.button(self.t('Скачать / обновить ADB','Download / update ADB'),lambda:self.download_tool('adb'))))
        self.scrcpy_path = QLineEdit(self.settings.values.get('scrcpy',''))
        self.scrcpy_path.setPlaceholderText(self.t('Полный путь к scrcpy.exe','Full path to scrcpy.exe'))
        box.addWidget(self.label('scrcpy / Genymobile'))
        box.addWidget(self.scrcpy_path)
        box.addLayout(self.row(self.button(self.t('Выбрать scrcpy.exe','Choose scrcpy.exe'),lambda:self.choose_tool('scrcpy')),
                               self.button(self.t('Скачать / обновить scrcpy','Download / update scrcpy'),lambda:self.download_tool('scrcpy'))))
        box.addWidget(self.button(self.t('Сохранить пути','Save tool paths'),self.save_tool_paths,True))
        layout.addWidget(card)
        card, box = self.card()
        self.theme = QCheckBox(self.t('Светлая тема','Light theme'))
        self.theme.setChecked(self.light)
        self.theme.toggled.connect(self.change_theme)
        box.addWidget(self.theme)
        self.language = QComboBox()
        self.language.addItems(['Русский','English'])
        self.language.setCurrentIndex(1 if self.lang=='en' else 0)
        self.language.currentIndexChanged.connect(self.change_language)
        box.addWidget(self.language)
        self.repo_input = QLineEdit(self.settings.values.get('repository','cokker/QuestToolbox'))
        box.addWidget(self.label(self.t('Репозиторий обновлений','Update repository')))
        box.addWidget(self.repo_input)
        self.preview_updates = QCheckBox(self.t('Учитывать предварительные версии (Preview)','Include preview releases'))
        self.preview_updates.setChecked(self.settings.values.get('preview_updates', True))
        box.addWidget(self.preview_updates)
        box.addWidget(self.button(self.t('Проверить релизы GitHub','Check GitHub releases'),self.updates))
        box.addWidget(self.label(self.t('Обновление скачивается с выбранной страницы релиза после твоего подтверждения. Самозамена EXE и фоновая установка отключены.','Updates are downloaded from the selected release page after confirmation. No background installation or executable replacement.'),'muted'))
        layout.addWidget(card)
        layout.addWidget(self.label(self.t('Независимый проект, не связан с Meta. Не выполняет root, разблокировку загрузчика или изменение прошивки.','Independent project, not affiliated with Meta. No rooting, bootloader unlocking or firmware flashing.'),'muted'))
        layout.addStretch()

    def table_setup(self, table):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setShowGrid(False)

    def serial(self):
        return self.selector.currentData() or ''

    def update_connection_badge(self):
        device = next((d for d in self.devices if d.serial == self.serial()), None)
        if not device:
            label = self.t('Нет подключения', 'Disconnected')
        elif device.state == 'unauthorized':
            label = self.t('Разреши отладку в шлеме', 'Authorize in headset')
        elif device.state != 'device':
            label = self.t('Шлем не отвечает', 'Headset offline')
        else:
            label = 'Wi-Fi' if ':' in device.serial else 'USB'
        self.connection_badge.setText(label)

    def adb(self, progress=None, require=True):
        serial = self.serial()
        if require and not any(d.serial==serial and d.state=='device' for d in self.devices):
            raise ToolboxError(self.t('Выберите подключённый и авторизованный шлем.','Choose a connected and authorized headset.'))
        return Adb(find_adb(self.settings.values.get('adb','')), serial, self.cancel, progress)

    def set_busy(self, busy, title=''):
        self.busy = busy
        self.selector.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.stack.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.progressbar.setRange(0,0 if busy else 1)
        if title:
            self.status.setText(title)

    def run(self,title,function,callback=None,quiet=False):
        if self.busy:
            return
        self.cancel = threading.Event()
        self.set_busy(True, '' if quiet else title)
        task = Task(function)
        self.current_task = task
        def done(value):
            self.set_busy(False)
            if not quiet:
                self.record(title, True)
                self.status.setText(self.t('Готово: ','Done: ')+title)
            if callback:
                try:
                    callback(value)
                except Exception as e:
                    self.error(str(e))
        def failed(message):
            self.set_busy(False)
            if not quiet:
                self.record(title,False)
                self.error(message)
            else:
                self.status.setText(message[:200])
        task.signals.progress.connect(self.status.setText)
        task.signals.done.connect(done)
        task.signals.failed.connect(failed)
        self.pool.start(task)

    def operation(self, title, function, callback=None):
        # Capture selected device and executable on the UI thread before dispatching.
        adb = self.adb()
        self.run(title, lambda progress: self.with_adb(adb,progress,function), callback)

    def with_adb(self,adb,progress,function):
        adb.cancel = self.cancel
        adb.progress = progress
        return function(adb)

    def error(self,message):
        self.status.setText(self.t('Операция не завершена','Operation did not complete'))
        box = QMessageBox(self)
        box.setWindowTitle(self.t('Quest Toolbox — ошибка','Quest Toolbox — error'))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(message[:800])
        if len(message)>800:
            box.setDetailedText(message)
        box.exec()

    def confirm(self,text):
        return QMessageBox.question(self,self.t('Подтверждение','Confirm'),text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def record(self,title,success):
        self.history.append(f'{time.strftime("%Y-%m-%d %H:%M:%S")}  {"OK" if success else "ERROR"}  {title}')
        self.history = self.history[-300:]
        self.settings.values['history'] = self.history
        try:
            self.settings.save()
        except OSError:
            pass
        self.refresh_history()

    def refresh_history(self):
        self.history_view.setPlainText('\n'.join(reversed(self.history)))

    def clear_history(self):
        self.history=[]
        self.settings.values['history']=[]
        self.settings.save()
        self.refresh_history()

    def poll(self):
        if not self.busy and not self.log_process and not self.mirror_process:
            self.scan(quiet=True)

    def scan(self,quiet=False):
        adb=self.adb(require=False)
        def got(devices):
            old=self.serial()
            self.devices=devices
            self.selector.blockSignals(True)
            self.selector.clear()
            nicknames=self.settings.values.get('nicknames',{})
            states={'device':self.t('подключён','connected'),'unauthorized':self.t('разреши отладку','authorize debugging'),
                    'offline':self.t('не отвечает','offline')}
            for d in devices:
                name=nicknames.get(d.serial,d.model or d.serial)
                self.selector.addItem(f'{name} · {states.get(d.state,d.state)} · {d.serial}',d.serial)
            if not devices:
                self.selector.addItem(self.t('Шлем не найден','No headset found'),None)
            idx=self.selector.findData(old)
            if idx>=0:
                self.selector.setCurrentIndex(idx)
            else:
                idx=next((i for i,d in enumerate(devices) if d.state=='device'),0)
                self.selector.setCurrentIndex(idx)
            self.selector.blockSignals(False)
            if self.serial()!=old or not devices:
                self.selected()
            if devices and (not quiet or self.snapshot_serial!=self.serial()):
                if any(d.serial==self.serial() and d.state=='device' for d in devices):
                    QTimer.singleShot(0,self.read_snapshot)
            self.update_connection_badge()
        self.run(self.t('Поиск устройств','Scanning devices'),lambda p:self.with_adb(adb,p,lambda a:a.devices()),got,quiet)

    def selected(self):
        self.update_connection_badge()
        self.stop_log()
        self.stop_mirror()
        self.snapshot=None
        self.snapshot_serial=''
        self.app_table.setRowCount(0)
        self.file_table.setRowCount(0)
        self.model_label.setText(self.t('Обнови состояние шлема','Refresh headset status'))
        self.model_detail.setText(self.t('Данные ещё не считаны','Device details not read yet'))
        for label in self.stats.values():
            label.setText('—')
        self.update_display()

    def read_snapshot(self):
        serial=self.serial()
        def got(data):
            if serial!=self.serial():
                return
            self.snapshot=data
            self.snapshot_serial=serial
            props=data['props']
            self.model_label.setText(data['model'] or props.get('ro.product.model','Android'))
            self.model_detail.setText('Android '+props.get('ro.build.version.release','?')+'  /  '+props.get('ro.build.version.incremental','?'))
            level=re.search(r'^\s*level:\s*(\d+)',data['battery'],re.M)
            temp=re.search(r'^\s*temperature:\s*(\d+)',data['battery'],re.M)
            self.stats['battery'].setText((level[1]+' %' if level else '—')+(f' · {int(temp[1])/10:g} °C' if temp else ''))
            ip=re.search(r'inet\s+([\d.]+)',data['ip'])
            self.stats['ip'].setText(ip[1] if ip else '—')
            if ip:
                self.address.setText(ip[1]+':5555')
            disk=data['disk'].splitlines()
            self.stats['storage'].setText('—')
            for line in disk[1:]:
                cols=line.split()
                if len(cols)>=4 and cols[3].isdigit():
                    self.stats['storage'].setText(f'{int(cols[3])/1024/1024:.1f} GB')
                    break
            if data['warnings']:
                self.status.setText(self.t('Часть данных недоступна на этой прошивке','Some data is unavailable on this firmware'))
            self.update_display()
        self.operation(self.t('Состояние шлема','Headset status'),lambda a:a.snapshot(),got)

    def device_command(self,args,title=None):
        self.operation(title or self.t('Команда устройства','Device command'),lambda a:a.command(args),lambda value:self.status.setText(str(value)[:300] or self.t('Команда выполнена','Command completed')))

    def reboot(self):
        self.adb()
        if self.confirm(self.t('Перезапустить выбранный шлем? Приложения и текущая запись будут остановлены.','Reboot the selected headset? Running apps and recording will stop.')):
            self.device_command(['reboot'],self.t('Перезапуск шлема','Reboot headset'))

    def rename_device(self):
        serial=self.adb().serial
        name,ok=QInputDialog.getText(self,self.t('Имя шлема','Headset name'),self.t('Новое имя:','New name:'))
        if ok and name.strip():
            self.settings.values.setdefault('nicknames',{})[serial]=name.strip()[:60]
            self.settings.save()
            self.scan()

    def enable_wifi(self):
        adb=self.adb()
        if ':' in adb.serial:
            raise ToolboxError(self.t('Для первоначальной настройки выберите USB-подключение.','Select the USB connection for initial setup.'))
        if not self.confirm(self.t('Включить ADB на порту 5555? Используй только доверенную домашнюю сеть.','Enable ADB on port 5555? Use a trusted home network.')):
            return
        def work(a):
            output=a.shell('ip','-o','-4','addr','show','wlan0')
            match=re.search(r'inet\s+([\d.]+)',output)
            if not match:
                raise ToolboxError('Шлем не получил IPv4-адрес Wi-Fi.')
            a.command(['tcpip','5555'])
            return match[1]+':5555'
        def got(address):
            self.address.setText(address)
            self.settings.values['endpoint']=address
            self.settings.save()
            self.status.setText(self.t('Wi-Fi ADB включён. Нажми «Подключиться».','Wi-Fi ADB enabled. Click Connect.'))
        self.operation(self.t('Включение Wi-Fi ADB','Enabling Wi-Fi ADB'),work,got)

    def connect_wifi(self):
        address=endpoint(self.address.text())
        adb=self.adb(require=False)
        def work(p):
            adb.cancel=self.cancel
            result=adb.command(['connect',address],timeout=20,device=False)
            if not any(d.serial==address and d.state=='device' for d in adb.devices()):
                raise ToolboxError('ADB не подтвердил подключение.\n'+result)
            return address
        def got(value):
            self.settings.values['endpoint']=value
            self.settings.save()
            self.scan()
        self.run(self.t('Подключение по Wi-Fi','Connecting via Wi-Fi'),work,got)

    def disconnect_wifi(self):
        address=endpoint(self.address.text())
        adb=self.adb(require=False)
        self.run(self.t('Отключение Wi-Fi соединения','Disconnecting Wi-Fi session'),lambda p:self.with_adb(adb,p,lambda a:a.command(['disconnect',address],device=False)),lambda _:self.scan())

    def disable_wifi(self):
        if self.confirm(self.t('Вернуть ADB в режим USB? Беспроводное соединение оборвётся.','Return ADB to USB mode? The wireless connection will drop.')):
            self.device_command(['usb'],self.t('Отключение Wi-Fi ADB','Disabling Wi-Fi ADB'))

    def restart_adb(self):
        if not self.confirm(self.t('Перезапустить ADB? Это также разорвёт ADB-соединения других программ на ПК.','Restart ADB? This also disconnects other ADB applications on this PC.')):
            return
        adb=self.adb(require=False)
        self.stop_log()
        self.stop_mirror()
        def work(a):
            a.command(['kill-server'],device=False)
            return a.command(['start-server'],device=False)
        self.run(self.t('Перезапуск ADB','Restarting ADB'),lambda p:self.with_adb(adb,p,work),lambda _:self.scan())

    def choose_apk(self,split=False):
        self.adb()
        paths,_=QFileDialog.getOpenFileNames(self,'APK','','APK (*.apk)')
        if paths:
            self.install_paths(paths,split)

    def install_paths(self,paths,split=False):
        if not self.confirm(self.t('Установить на выбранный шлем следующие APK?\n','Install these APKs on the selected headset?\n')+'\n'.join(Path(x).name for x in paths)):
            return
        self.operation(self.t('Установка APK','Installing APK'),lambda a:a.install(paths,split),lambda value:self.status.setText(value))

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.busy:
            paths=[u.toLocalFile() for u in event.mimeData().urls()]
            if paths and all(Path(p).suffix.lower()=='.apk' for p in paths):
                event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls()]
        self.guard(lambda:self.install_paths(paths))

    def load_apps(self):
        system=self.system_apps.isChecked()
        serial=self.serial()
        def got(apps):
            self.apps_serial=serial
            self.app_table.setRowCount(len(apps))
            for i,name in enumerate(apps):
                self.app_table.setItem(i,0,QTableWidgetItem(name))
            self.filter_apps()
        self.operation(self.t('Список приложений','Loading apps'),lambda a:a.list_apps(system),got)

    def system_apps_changed(self):
        self.app_table.setRowCount(0)
        self.apps_serial = ''
        if any(d.serial == self.serial() and d.state == 'device' for d in self.devices):
            self.load_apps()

    def filter_apps(self):
        needle=self.app_filter.text().lower()
        for i in range(self.app_table.rowCount()):
            self.app_table.setRowHidden(i,needle not in self.app_table.item(i,0).text().lower())

    def current_app(self):
        self.adb()
        row=self.app_table.currentRow()
        if row<0 or self.app_table.isRowHidden(row) or getattr(self,'apps_serial','')!=self.serial():
            raise ToolboxError(self.t('Выберите приложение из актуального списка.','Select an app from the current list.'))
        return package_name(self.app_table.item(row,0).text())

    def launch_app(self):
        package=self.current_app()
        self.operation(self.t('Запуск приложения','Launching app'),lambda a:a.launch(package))

    def stop_app(self):
        package=self.current_app()
        if self.confirm(self.t('Принудительно остановить ','Force stop ')+package+'?'):
            self.operation(self.t('Остановка приложения','Stopping app'),lambda a:a.shell('am','force-stop',package))

    def app_details(self):
        package=self.current_app()
        self.operation(self.t('Сведения о приложении','App details'),lambda a:a.shell('dumpsys','package',package),lambda value:self.text_dialog(package,value))

    def refresh_favorites(self):
        self.favorites.clear()
        entries=self.settings.values.get('favorites',[])
        if not entries:
            self.favorites.addItem(self.t('Избранных приложений пока нет','No favorite apps yet'),None)
        for package in entries:
            self.favorites.addItem(package,package)

    def toggle_favorite(self):
        package=self.current_app()
        entries=self.settings.values.setdefault('favorites',[])
        if package in entries:
            entries.remove(package)
        else:
            entries.append(package)
        self.settings.save()
        self.refresh_favorites()

    def launch_favorite(self):
        package=self.favorites.currentData()
        if not package:
            raise ToolboxError(self.t('Добавьте приложение в избранное в разделе «Приложения».','Add a favorite in the Apps section first.'))
        self.operation(self.t('Запуск избранного','Launching favorite'),lambda a:a.launch(package))

    def export_apk(self):
        package=self.current_app()
        folder=QFileDialog.getExistingDirectory(self,self.t('Куда сохранить APK','APK destination'))
        if folder:
            target=Path(folder)/package
            if target.exists() and not self.confirm(self.t('Папка пакета уже существует. Совпадающие файлы будут заменены. Продолжить?','Package folder already exists. Matching files will be overwritten. Continue?')):
                return
            self.operation(self.t('Экспорт APK','Exporting APK'),lambda a:a.export_apk(package,folder),lambda value:self.status.setText(value))

    def uninstall_app(self):
        package=self.current_app()
        if not self.confirm(self.t('Удалить приложение и его данные?\n','Remove the app and its data?\n')+package):
            return
        def work(a):
            if package not in a.list_apps(False):
                raise ToolboxError('Удаление системных пакетов отключено.')
            result=a.command(['uninstall',package],timeout=120)
            if 'Success' not in result:
                raise ToolboxError(result)
            return result
        self.operation(self.t('Удаление приложения','Uninstalling app'),work,lambda _:self.load_apps())

    def open_folder(self,path):
        self.folder.setText(path)
        self.load_files()

    def parent_folder(self):
        folder=remote_path(self.folder.text())
        self.open_folder('/sdcard' if folder=='/sdcard' else str(PurePosixPath(folder).parent))

    def load_files(self):
        folder=remote_path(self.folder.text())
        serial=self.serial()
        def got(entries):
            self.listed_folder=folder
            self.files_serial=serial
            self.file_table.setRowCount(len(entries))
            for i,(name,isdir) in enumerate(entries):
                item=QTableWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole,isdir)
                self.file_table.setItem(i,0,item)
                self.file_table.setItem(i,1,QTableWidgetItem(self.t('Папка','Folder') if isdir else self.t('Файл','File')))
        self.operation(self.t('Чтение папки','Reading folder'),lambda a:a.list_files(folder),got)

    def current_file(self):
        self.adb()
        row=self.file_table.currentRow()
        if row<0 or self.folder.text()!=getattr(self,'listed_folder',None) or getattr(self,'files_serial','')!=self.serial():
            raise ToolboxError(self.t('Обновите папку и выберите файл.','Refresh the folder and select an item.'))
        item=self.file_table.item(row,0)
        return remote_path(self.listed_folder+'/'+item.text()),bool(item.data(Qt.ItemDataRole.UserRole))

    def enter_file(self,row,column):
        def action():
            path,isdir=self.current_file()
            if isdir:
                self.open_folder(path)
        self.guard(action)

    def upload_files(self):
        self.adb()
        folder=remote_path(self.folder.text())
        paths,_=QFileDialog.getOpenFileNames(self,self.t('Отправить файлы','Upload files'))
        if paths and self.confirm(self.t('Отправить файлы в эту папку? Совпадающие имена будут перезаписаны.\n','Upload to this folder? Matching filenames will be overwritten.\n')+folder):
            self.operation(self.t('Передача файлов','Uploading files'),lambda a:a.push_files(paths,folder),lambda _:self.load_files())

    def download_file(self):
        remote,isdir=self.current_file()
        folder=QFileDialog.getExistingDirectory(self,self.t('Папка на компьютере','Destination folder'))
        if not folder:
            return
        target=Path(folder)/PurePosixPath(remote).name
        if target.exists() and not self.confirm(self.t('Файл или папка уже существует. Перезаписать совпадающие файлы?','Destination exists. Overwrite matching files?')):
            return
        # Pull into parent so adb retains the original directory name exactly once.
        self.operation(self.t('Скачивание со шлема','Downloading from headset'),lambda a:a.command(['pull',remote,folder],timeout=1800))

    def new_folder(self):
        parent=remote_path(self.folder.text())
        name,ok=QInputDialog.getText(self,self.t('Создать папку','New folder'),self.t('Имя:','Name:'))
        if ok and name:
            if '/' in name or name in ('.','..'):
                raise ToolboxError('Недопустимое имя папки.')
            path=remote_path(parent+'/'+name)
            self.operation(self.t('Создание папки','Creating folder'),lambda a:a.shell('mkdir',path),lambda _:self.load_files())

    def delete_file(self):
        path,isdir=self.current_file()
        if self.confirm(self.t('Удалить безвозвратно?\n','Delete permanently?\n')+path):
            self.operation(self.t('Удаление файла','Deleting file'),lambda a:a.shell('rm','-r' if isdir else '-f','--',path),lambda _:self.load_files())

    def known_model(self):
        if not self.snapshot or self.snapshot_serial!=self.serial() or not self.snapshot.get('model'):
            raise ToolboxError(self.t('Сначала считайте состояние поддерживаемого Quest на главной странице.','Read a supported Quest status on the Overview page first.'))
        return self.snapshot['model']

    def update_display(self):
        model=self.snapshot.get('model') if self.snapshot else None
        self.refresh_rate.clear()
        self.refresh_rate.addItem(self.t('Не менять частоту','Keep current refresh rate'),None)
        for hz in RATES.get(model,()):
            self.refresh_rate.addItem(f'{hz} Hz',hz)
        self.apply_display_button.setEnabled(model in RATES)
        self.display_note.setText((model+' · '+', '.join(map(str,RATES[model]))+' Hz') if model else self.t('Сначала обнови состояние шлема. Для неизвестной модели запись настроек отключена.','Refresh headset status first. Unknown models cannot change display properties.'))
        self.profiles.clear()
        for name,profile in self.settings.values.get('profiles',{}).items():
            if profile.get('model')==model:
                self.profiles.addItem(name)

    def display_changes(self):
        changes={}
        hz=self.refresh_rate.currentData()
        if hz:
            changes['debug.oculus.refreshRate']=str(hz)
        if self.use_texture.isChecked():
            changes['debug.oculus.textureWidth']=str(self.texture_w.value())
            changes['debug.oculus.textureHeight']=str(self.texture_h.value())
        if self.dynamic_ffr.currentIndex():
            changes['debug.oculus.foveation.dynamic']=str(self.dynamic_ffr.currentIndex()-1)
        return changes

    def apply_properties(self,changes):
        model=self.known_model()
        serial=self.serial()
        if not changes:
            raise ToolboxError(self.t('Не выбраны изменения.','No changes selected.'))
        if not self.confirm(self.t('Применить к ','Apply to ')+model+'?\n\n'+'\n'.join(f'{k}: {v}' for k,v in changes.items())):
            return
        def got(previous):
            saved=self.previous.setdefault(serial,{})
            for key,value in previous.items():
                saved.setdefault(key,value)
            self.status.setText(self.t('Свойства записаны и прочитаны обратно. Реальный FPS не измерялся.','Properties written and read back. Actual FPS was not measured.'))
        self.operation(self.t('Применение настроек','Applying settings'),lambda a:a.apply_properties(changes,model),got)

    def apply_display(self):
        self.apply_properties(self.display_changes())

    def restore_display(self):
        serial=self.serial()
        previous=self.previous.get(serial)
        if not previous:
            raise ToolboxError(self.t('В этом сеансе ещё не сохранены исходные значения. Для сброса временных свойств перезагрузите шлем.','No original values saved in this session. Reboot the headset to reset temporary properties.'))
        if self.confirm(self.t('Восстановить исходные свойства дисплея и записи, изменённые в этом сеансе?','Restore original display and recording properties changed in this session?')):
            def got(value):
                self.previous.pop(serial,None)
                self.status.setText(value)
            self.operation(self.t('Восстановление настроек','Restoring properties'),lambda a:a.restore_properties(previous),got)

    def read_display(self):
        from .core import PROPERTY_KEYS
        def work(a):
            return '\n'.join(key+' = '+(a.getprop(key) or '(not overridden)') for key in sorted(PROPERTY_KEYS))
        self.operation(self.t('Чтение свойств','Reading properties'),work,lambda value:self.text_dialog(self.t('Текущие свойства','Current properties'),value))

    def save_profile(self):
        model=self.known_model()
        changes=self.display_changes()
        from .core import validate_properties
        validate_properties(changes,model)
        if not changes:
            raise ToolboxError('Выберите хотя бы один параметр.')
        name,ok=QInputDialog.getText(self,self.t('Сохранить профиль','Save profile'),self.t('Название:','Name:'))
        if ok and name.strip():
            name=name.strip()[:80]
            profiles=self.settings.values.setdefault('profiles',{})
            if name in profiles and not self.confirm(self.t('Заменить существующий профиль?','Replace existing profile?')):
                return
            profiles[name]={'model':model,'changes':changes}
            self.settings.save()
            self.update_display()

    def load_profile(self):
        name=self.profiles.currentText()
        profile=self.settings.values.get('profiles',{}).get(name)
        if not profile or profile['model']!=self.known_model():
            raise ToolboxError('Выберите профиль для этой модели.')
        changes=profile['changes']
        hz=changes.get('debug.oculus.refreshRate')
        self.refresh_rate.setCurrentIndex(max(0,self.refresh_rate.findData(int(hz)) if hz else 0))
        self.use_texture.setChecked('debug.oculus.textureWidth' in changes)
        self.texture_w.setValue(int(changes.get('debug.oculus.textureWidth',1440)))
        self.texture_h.setValue(int(changes.get('debug.oculus.textureHeight',1584)))
        ffr=changes.get('debug.oculus.foveation.dynamic')
        self.dynamic_ffr.setCurrentIndex(int(ffr)+1 if ffr is not None else 0)
        self.status.setText(self.t('Профиль загружен в форму. Нажми «Применить».','Profile loaded into form. Click Apply.'))

    def delete_profile(self):
        name=self.profiles.currentText()
        if name and self.confirm(self.t('Удалить профиль ','Delete profile ')+name+'?'):
            self.settings.values.get('profiles',{}).pop(name,None)
            self.settings.save()
            self.update_display()

    def apply_capture(self):
        self.apply_properties({'debug.oculus.capture.width':str(self.video_w.value()),
                               'debug.oculus.capture.height':str(self.video_h.value()),
                               'debug.oculus.capture.bitrate':str(self.video_bitrate.value()*1_000_000),
                               'debug.oculus.fullRateCapture':str(int(self.full_capture.isChecked()))})

    def screenshot(self):
        self.adb()
        path,_=QFileDialog.getSaveFileName(self,self.t('Снимок экрана','Screenshot'),'Quest-screenshot.png','PNG (*.png)')
        if path:
            self.operation(self.t('Снимок экрана','Screenshot'),lambda a:a.screenshot(path))

    def start_mirror(self,record=False):
        adb=self.adb()
        if self.mirror_process:
            raise ToolboxError(self.t('Сначала остановите текущую трансляцию.','Stop the current mirror session first.'))
        executable=self.settings.values.get('scrcpy','')
        if not executable or not Path(executable).is_file():
            self.nav.setCurrentRow(8)
            raise ToolboxError(self.t('Выберите или скачайте scrcpy в настройках.','Select or download scrcpy in Settings.'))
        args=['--serial',adb.serial,'--no-control','--max-size',self.capture_size.currentText(),'--max-fps','60','--video-codec=h264']
        if not self.capture_audio.isChecked():
            args.append('--no-audio')
        if record:
            path,_=QFileDialog.getSaveFileName(self,self.t('Запись экрана','Screen recording'),'Quest-recording.mp4','MP4 (*.mp4)')
            if not path:
                return
            args+=['--record',path]
        p=QProcess(self)
        env=QProcessEnvironment.systemEnvironment()
        env.insert('ADB',adb.executable)
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(str(Path(executable).parent))
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.mirror_output=''
        def output():
            self.mirror_output=(self.mirror_output+bytes(p.readAllStandardOutput()).decode('utf-8','replace'))[-6000:]
            lines=self.mirror_output.strip().splitlines()
            if lines:
                self.mirror_status.setText(lines[-1][:250])
        def finished(code,status):
            output()
            if self.mirror_process is p:
                self.mirror_process=None
            self.mirror_status.setText(self.t('Трансляция завершена','Mirroring ended')+f' · code {code}')
            if code:
                self.text_dialog('scrcpy',self.mirror_output or str(p.errorString()))
            p.deleteLater()
        p.readyReadStandardOutput.connect(output)
        p.finished.connect(finished)
        def failed(error):
            if error==QProcess.ProcessError.FailedToStart:
                self.mirror_process=None
                self.error(p.errorString())
                p.deleteLater()
        p.errorOccurred.connect(failed)
        self.mirror_process=p
        p.started.connect(lambda:self.record(self.t('Запуск scrcpy','Starting scrcpy'),True))
        p.start(executable,args)
        self.mirror_status.setText(self.t('Запуск scrcpy… Закрой окно scrcpy для корректного завершения записи.','Starting scrcpy… Close its window to finalize a recording.'))

    def stop_mirror(self):
        p=self.mirror_process
        if p and p.state()!=QProcess.ProcessState.NotRunning:
            # On Windows Qt sends WM_CLOSE; scrcpy handles the SDL window close.
            p.terminate()
            self.mirror_status.setText(self.t('Останавливается… Если окно не закрывается, закрой его вручную.','Stopping… Close the scrcpy window manually if necessary.'))

    def start_log(self):
        adb=self.adb()
        if self.log_process:
            raise ToolboxError(self.t('Сначала остановите текущий журнал и дождитесь завершения процесса.','Stop the current log stream and wait for it to finish first.'))
        p=QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.log_partial=''
        self.log_decoder=__import__('codecs').getincrementaldecoder('utf-8')('replace')
        serial=adb.serial
        def output():
            self.log_partial+=self.log_decoder.decode(bytes(p.readAllStandardOutput()))
            lines=self.log_partial.split('\n')
            self.log_partial=lines.pop()
            if len(self.log_partial)>131072:
                self.log_partial=self.log_partial[-131072:]
            needle=self.log_filter.text().lower()
            for line in lines:
                if not needle or needle in line.lower():
                    self.log_view.appendPlainText(redact(line,(serial,)))
        def done(code,status):
            output()
            if self.log_process is p:
                self.log_process=None
            p.deleteLater()
        p.readyReadStandardOutput.connect(output)
        p.finished.connect(done)
        def failed(error):
            self.log_view.appendPlainText(p.errorString())
            if error==QProcess.ProcessError.FailedToStart:
                if self.log_process is p:
                    self.log_process=None
                p.deleteLater()
        p.errorOccurred.connect(failed)
        self.log_process=p
        p.start(adb.executable,['-s',serial,'logcat','-v','threadtime','-T','1','*:'+self.log_level.currentText()])

    def stop_log(self):
        p=self.log_process
        if p and p.state()!=QProcess.ProcessState.NotRunning:
            p.terminate()
            # Keep the reference until finished, preventing window destruction
            # while QProcess still owns a live child process.
            timer=QTimer(p)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: p.kill() if p.state()!=QProcess.ProcessState.NotRunning else None)
            timer.start(2000)

    def save_logs(self):
        path,_=QFileDialog.getSaveFileName(self,self.t('Сохранить журнал','Save log'),'quest-log.txt','Text (*.txt)')
        if path:
            Path(path).write_text(redact(self.log_view.toPlainText(),(self.serial(),)),'utf-8')

    def build_report(self):
        self.operation(self.t('Сбор диагностики','Collecting diagnostics'),lambda a:a.diagnostics(),lambda value:self.text_dialog(self.t('Проверь отчёт перед сохранением','Review report before saving'),value,save=True))

    def text_dialog(self,title,text,save=False):
        dialog=QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820,600)
        layout=QVBoxLayout(dialog)
        view=QPlainTextEdit()
        view.setReadOnly(not save)
        view.setPlainText(text)
        layout.addWidget(view)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        if save:
            button=buttons.addButton(self.t('Сохранить отчёт','Save report'),QDialogButtonBox.ButtonRole.ActionRole)
            def write():
                path,_=QFileDialog.getSaveFileName(dialog,self.t('Сохранить','Save'),'quest-diagnostics.txt','Text (*.txt)')
                if path:
                    try:
                        Path(path).write_text(view.toPlainText(),'utf-8')
                        dialog.accept()
                    except OSError as e:
                        self.error(str(e))
            button.clicked.connect(write)
        layout.addWidget(buttons)
        dialog.exec()

    def choose_tool(self,kind):
        path,_=QFileDialog.getOpenFileName(self,kind,'','Executable (*.exe);;All files (*)')
        if path:
            (self.adb_path if kind=='adb' else self.scrcpy_path).setText(path)
            self.save_tool_paths()

    def save_tool_paths(self):
        paths={}
        for key,widget in [('adb',self.adb_path),('scrcpy',self.scrcpy_path)]:
            value=widget.text().strip().strip('"')
            if value and not Path(value).is_file():
                raise ToolboxError(self.t('Файл не найден: ','File not found: ')+value)
            paths[key]=value
        self.settings.values.update(paths)
        self.settings.save()
        self.status.setText(self.t('Пути сохранены','Tool paths saved'))

    def download_tool(self,kind):
        if kind=='adb':
            message=self.t('Загрузить Android SDK Platform-Tools с dl.google.com? Перед продолжением ознакомься с условиями Google Android SDK: https://developer.android.com/studio/terms\n\nПродолжить загрузку, принимая эти условия?','Download Android SDK Platform-Tools from dl.google.com? Review the Google Android SDK terms at https://developer.android.com/studio/terms\n\nAccept the terms and download?')
        else:
            message=self.t('Скачать scrcpy из официального GitHub Genymobile/scrcpy?','Download scrcpy from the official Genymobile/scrcpy GitHub repository?')
        if not self.confirm(message):
            return
        def got(path):
            self.settings.values[kind]=path
            self.settings.save()
            (self.adb_path if kind=='adb' else self.scrcpy_path).setText(path)
            self.status.setText(self.t('Инструмент установлен','Tool installed'))
        self.run(self.t('Загрузка ','Downloading ')+kind,lambda progress:install_tool(kind,self.cancel,progress),got)

    def change_theme(self,checked):
        self.light=checked
        self.settings.values['light']=checked
        self.settings.save()
        QApplication.instance().setStyleSheet(stylesheet(checked))

    def change_language(self,index):
        self.settings.values['language']='en' if index else 'ru'
        self.settings.save()
        QMessageBox.information(self,'Language / Язык',self.t('Язык интерфейса изменится после перезапуска Toolbox. Текущие операции не прерываются.','The interface language will change after restarting Toolbox. Current operations are unaffected.'))

    def updates(self):
        repo=self.repo_input.text().strip()
        include_previews=self.preview_updates.isChecked()
        self.settings.values['repository']=repo
        self.settings.values['preview_updates']=include_previews
        self.settings.save()
        def got(info):
            tag=info.get('tag_name','?')
            current=tuple(map(int,__version__.split('.')))
            match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z0-9.-]+)?',tag)
            newer=match and tuple(map(int,match.groups()))>current
            title=self.t('Доступна новая версия: ','New version available: ') if newer else self.t('Последний релиз: ','Latest release: ')
            if self.confirm(title+tag+'\n\n'+info.get('body','')[:1400]+'\n\n'+self.t('Открыть страницу релиза для скачивания?','Open the release download page?')):
                self.open_url(info['html_url'])
        self.run(self.t('Проверка обновлений','Checking updates'),lambda p:check_update(repo,self.cancel,p,include_previews),got)

    def open_url(self,url):
        QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self,event):
        active=self.busy or bool(self.mirror_process) or bool(self.log_process)
        if active:
            if self.confirm(self.t('Есть активные операции. Остановить их? При записи дождись закрытия окна scrcpy, затем закрой Toolbox ещё раз.','Operations are running. Stop them? If recording, wait for scrcpy to close, then close Toolbox again.')):
                self.cancel.set()
                self.stop_log()
                self.stop_mirror()
            event.ignore()
            return
        self.timer.stop()
        self.settings.save()
        event.accept()


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('Quest Toolbox')
    app.setOrganizationName('COKKER')
    app.setStyle('Fusion')
    if '--smoke-test' in sys.argv:
        from .smoke import run_smoke
        index=sys.argv.index('--smoke-test')
        if index+1>=len(sys.argv):
            return 2
        return run_smoke(app,sys.argv[index+1])
    window=Window()
    window.show()
    return app.exec()
