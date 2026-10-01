import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import time
import pytest
from PySide6.QtWidgets import QApplication
from quest_toolbox.ui import Window
from quest_toolbox.core import Settings, Device

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def window(app,tmp_path):
    w=Window(Settings(tmp_path/'settings.json'),auto_scan=False)
    w.show(); app.processEvents()
    yield w
    w.close(); app.processEvents()


def test_all_pages_render_and_scroll(app,window,tmp_path):
    assert window.stack.count()==9
    window.resize(960,680)
    for i in range(9):
        window.nav.setCurrentRow(i); app.processEvents()
        assert window.stack.currentIndex()==i
        page=window.stack.currentWidget()
        assert page.widget().sizeHint().width()<=page.viewport().width()+25
    assert window.stack.widget(8).verticalScrollBar().maximum()>0


def test_pro_rejects_120_and_unknown_disables_write(window):
    window.snapshot={'model':'Quest Pro'}; window.update_display()
    assert window.refresh_rate.findData(120)==-1
    assert window.refresh_rate.findData(90)>0
    window.snapshot={'model':None}; window.update_display()
    assert not window.apply_display_button.isEnabled()


def test_selection_clears_previous_device_content(window):
    window.app_table.setRowCount(3); window.file_table.setRowCount(2)
    window.snapshot={'model':'Quest 3'}; window.snapshot_serial='A'
    window.selected()
    assert window.snapshot is None
    assert window.app_table.rowCount()==window.file_table.rowCount()==0


def test_background_job_finishes_on_ui(app,window):
    out=[]
    window.run('test',lambda progress:'result',out.append)
    deadline=time.monotonic()+3
    while not out and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    assert out==['result'] and not window.busy
    assert window.selector.isEnabled()


def test_light_and_english(app,tmp_path):
    s=Settings(tmp_path/'en.json'); s.values={'language':'en','light':True}
    w=Window(s,auto_scan=False)
    assert w.nav.item(0).text()=='Overview'
    w.show(); app.processEvents(); w.close()


def test_wheel_scroll_and_tab_restore(app,window):
    from PySide6.QtCore import Qt,QPoint,QPointF
    from PySide6.QtGui import QWheelEvent
    window.resize(960,680)
    window.nav.setCurrentRow(8);app.processEvents()
    area=window.stack.currentWidget()
    viewport=area.viewport()
    event=QWheelEvent(QPointF(20,20),QPointF(viewport.mapToGlobal(QPoint(20,20))),QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
    app.sendEvent(viewport,event);app.processEvents()
    position=area.verticalScrollBar().value()
    assert position>0
    window.nav.setCurrentRow(0);app.processEvents()
    window.nav.setCurrentRow(8);app.processEvents()
    assert area.verticalScrollBar().value()==position
    assert window.windowOpacity()==1.0


def test_stop_log_keeps_live_process_until_finished(app,window):
    import sys
    from PySide6.QtCore import QProcess
    process=QProcess(window)
    window.log_process=process
    process.start(sys.executable,['-c','import time;time.sleep(20)'])
    assert process.waitForStarted(2000)
    window.stop_log()
    assert window.log_process is process
    process.waitForFinished(3000)
    window.log_process=None


def test_packaged_smoke_entrypoint(app,tmp_path):
    from quest_toolbox.smoke import run_smoke
    assert run_smoke(app,tmp_path/'smoke')==0
    assert (tmp_path/'smoke/smoke-result.json').is_file()
