"""Offline smoke test of the *packaged executable*, including real Qt painting."""
import json
import traceback
from pathlib import Path
from .core import Settings, RATES


def run_smoke(app, destination):
    from .ui import Window
    target=Path(destination).resolve()
    target.mkdir(parents=True,exist_ok=True)
    checks=[]
    window=None
    try:
        window=Window(Settings(target/'smoke-settings.json'),auto_scan=False)
        window.resize(1220,840)
        window.show()
        app.processEvents()
        assert window.isVisible()
        checks.append('Native Qt window opened')
        assert window.model_label.fontMetrics().inFontUcs4(ord('Я')), 'Cyrillic font glyph missing'
        checks.append('Cyrillic font glyph available')
        for index in range(window.stack.count()):
            window.nav.setCurrentRow(index)
            app.processEvents()
            page=window.stack.currentWidget()
            assert window.stack.currentIndex()==index
            assert page.widget().width()<=page.viewport().width(), index
            assert page.horizontalScrollBar().maximum()==0, index
            image=window.grab()
            assert not image.isNull()
            assert image.save(str(target/f'page-{index}.png'))
        checks.append('All nine pages painted without horizontal clipping')
        for model,rates in RATES.items():
            window.snapshot={'model':model}
            window.update_display()
            actual=tuple(window.refresh_rate.itemData(i) for i in range(1,window.refresh_rate.count()))
            assert actual==rates
        window.snapshot={'model':None}
        window.update_display()
        assert not window.apply_display_button.isEnabled()
        checks.append('Quest model allow-lists and unknown-device gate')
        window.change_theme(True)
        app.processEvents()
        assert window.grab().save(str(target/'light-theme.png'))
        checks.append('Light theme painted')
        window.close()
        app.processEvents()
        window=None
        result={'ok':True,'checks':checks,'physical_headset_tested':False}
        code=0
    except Exception:
        result={'ok':False,'checks':checks,'error':traceback.format_exc()}
        code=1
    finally:
        if window is not None:
            window.close()
            app.processEvents()
    (target/'smoke-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return code
