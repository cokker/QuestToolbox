import os
import threading
import zipfile
from pathlib import Path
import pytest
from quest_toolbox.core import (Adb, ToolboxError, Cancelled, parse_devices, parse_props, identify_model,
    validate_properties, remote_path, endpoint, redact, Settings)
from quest_toolbox.downloads import safe_extract


def test_devices_states_and_models():
    devices=parse_devices('List of devices attached\nUSB123 device product:x model:Quest_3S transport_id:1\n192.168.1.4:5555 offline\nU2 unauthorized\n* daemon started successfully\n')
    assert [(x.model,x.state) for x in devices]==[('Quest 3S','device'),('','offline'),('','unauthorized')]


@pytest.mark.parametrize('raw,expected',[('Meta Quest 3S','Quest 3S'),('Quest_3','Quest 3'),('Quest Pro','Quest Pro'),('Oculus Quest 2','Quest 2'),('Quest','Quest'),('Future Quest','')])
def test_models(raw,expected):
    assert (identify_model({'ro.product.model':raw}) or '')==expected


def test_props_parse():
    assert parse_props('[ro.product.model]: [Quest Pro]\n[empty]: []')=={'ro.product.model':'Quest Pro','empty':''}


@pytest.mark.parametrize('path',['/sdcard/../data','/data/private','relative','/sdcard/a\nb','/sdcard/a\x00b'])
def test_reject_remote_paths(path):
    with pytest.raises(ToolboxError): remote_path(path)


def test_remote_unicode_and_quote():
    assert remote_path("/sdcard/Download/кот's файл.apk")=="/sdcard/Download/кот's файл.apk"


@pytest.mark.parametrize('address',['host; reboot','192.168.1.2:0','192.168.1.2:99999','0.0.0.0','224.0.0.1'])
def test_endpoint_invalid(address):
    with pytest.raises(ToolboxError): endpoint(address)


def test_endpoint_default():
    assert endpoint('192.168.1.3')=='192.168.1.3:5555'


def test_no_pro_overclock():
    with pytest.raises(ToolboxError): validate_properties({'debug.oculus.refreshRate':'120'},'Quest Pro')
    validate_properties({'debug.oculus.refreshRate':'90'},'Quest Pro')
    validate_properties({'debug.oculus.refreshRate':'120'},'Quest 3S')


def test_unknown_model_and_bad_property():
    with pytest.raises(ToolboxError): validate_properties({'debug.oculus.refreshRate':'90'},'Quest X')
    with pytest.raises(ToolboxError): validate_properties({'persist.foo':'1'},'Quest 3')
    with pytest.raises(ToolboxError): validate_properties({'debug.oculus.textureWidth':'1001'},'Quest 3')


class PropertyAdb(Adb):
    def __init__(self,fail=False,cancel_mid=False):
        super().__init__('fake','SERIAL')
        self.props={'debug.oculus.textureWidth':'','debug.oculus.textureHeight':'1584'}
        self.fail=fail
        self.cancel_mid=cancel_mid
    def shell(self,*args,**kwargs):
        if args[0]=='getprop': return self.props.get(args[1],'')
        if self.cancel_mid and args[1].endswith('textureHeight') and args[2]=='1600' and kwargs.get('honor_cancel',True):
            self.cancel.set()
            raise Cancelled('cancelled')
        if self.fail and args[1].endswith('textureHeight') and args[2]=='1600':
            raise ToolboxError('denied')
        self.props[args[1]]=args[2]
        return ''


def test_transaction_rolls_back_empty_original():
    adb=PropertyAdb(fail=True)
    with pytest.raises(ToolboxError,match='восстановлены'):
        adb.apply_properties({'debug.oculus.textureWidth':'1600','debug.oculus.textureHeight':'1600'},'Quest 2')
    assert adb.props=={'debug.oculus.textureWidth':'','debug.oculus.textureHeight':'1584'}


def test_cancel_rolls_back():
    adb=PropertyAdb(cancel_mid=True)
    with pytest.raises(ToolboxError):
        adb.apply_properties({'debug.oculus.textureWidth':'1600','debug.oculus.textureHeight':'1600'},'Quest 2')
    assert adb.props['debug.oculus.textureWidth']==''


def test_success_returns_original_values():
    adb=PropertyAdb()
    old=adb.apply_properties({'debug.oculus.textureWidth':'1600'},'Quest 2')
    assert old=={'debug.oculus.textureWidth':''}
    adb.restore_properties(old)
    assert adb.props['debug.oculus.textureWidth']==''


def test_shell_quotes_remote_arguments():
    adb=Adb('fake','device')
    calls=[]
    adb.command=lambda args,*a,**k:calls.append(args) or ''
    adb.shell('rm','--',"/sdcard/a'; reboot; '")
    import shlex
    assert shlex.split(calls[0][1])==['rm','--',"/sdcard/a'; reboot; '"]
    assert calls[0][0]=='shell'


def test_device_selection_required():
    with pytest.raises(ToolboxError,match='выберите'):
        Adb('fake').command(['reboot'])


def test_apk_install_requires_success(tmp_path):
    path=tmp_path/'a.apk'; path.write_bytes(b'APK')
    adb=Adb('fake','device')
    adb.command=lambda *a,**k:'Unexpected response'
    with pytest.raises(ToolboxError,match='не подтверждена'): adb.install([str(path)])


def test_split_install_is_one_transaction(tmp_path):
    files=[tmp_path/'base.apk',tmp_path/'split.apk']
    for f in files:f.touch()
    calls=[]
    adb=Adb('fake','device')
    adb.command=lambda args,**k:calls.append(args) or 'Success'
    adb.install(list(map(str,files)),split=True)
    assert len(calls)==1 and calls[0][:2]==['install-multiple','-r']


def test_screenshot_rejects_non_png(tmp_path):
    adb=Adb('fake','device'); adb.command=lambda *a,**k:b'Permission denied'
    with pytest.raises(ToolboxError): adb.screenshot(str(tmp_path/'x.png'))
    assert not (tmp_path/'x.png').exists()


def test_settings_atomic_and_corrupt(tmp_path):
    path=tmp_path/'config.json'; path.write_text('bad')
    settings=Settings(path); settings.values={'name':'Дракон'}; settings.save()
    assert Settings(path).values['name']=='Дракон'
    assert not path.with_suffix('.tmp').exists()


def test_zip_slip(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt','oops')
    target=tmp_path/'extract'; target.mkdir()
    with pytest.raises(ToolboxError): safe_extract(archive,target)
    assert not (tmp_path/'escape.txt').exists()


def test_redaction():
    value=redact('serial-1 192.168.1.2 aa:bb:cc:dd:ee:ff x@example.org Bearer veryprivate',('serial-1',))
    assert 'serial-1' not in value and 'veryprivate' not in value and '192.168' not in value


def test_real_subprocess_serial_timeout_and_cancel(tmp_path):
    import sys
    # A fake executable is not required: use Python itself with device=False.
    adb=Adb(sys.executable)
    assert adb.command(['-c','print("ok")'],device=False)=='ok'
    with pytest.raises(ToolboxError,match='Время ожидания'):
        adb.command(['-c','import time; time.sleep(10)'],device=False,timeout=.05)
    adb.cancel.set()
    with pytest.raises(Cancelled): adb.command(['-c','print("no")'],device=False)


def test_preview_update_channel(monkeypatch):
    import json
    import quest_toolbox.downloads as downloads
    releases=[{'tag_name':'v0.1.0','prerelease':True,'html_url':'https://github.com/cokker/QuestToolbox/releases/tag/v0.1.0'},
              {'tag_name':'v0.0.9','prerelease':False,'html_url':'https://github.com/cokker/QuestToolbox/releases/tag/v0.0.9'}]
    urls=[]
    def fetch(url,*a):
        urls.append(url);return json.dumps(releases).encode()
    monkeypatch.setattr(downloads,'fetch',fetch)
    assert downloads.check_update('cokker/QuestToolbox',threading.Event(),lambda _:None)['tag_name']=='v0.1.0'
    assert downloads.check_update('cokker/QuestToolbox',threading.Event(),lambda _:None,False)['tag_name']=='v0.0.9'
    assert '/releases?per_page=' in urls[0]


def test_empty_update_channel_is_readable(monkeypatch):
    import quest_toolbox.downloads as downloads
    monkeypatch.setattr(downloads,'fetch',lambda *a:b'[]')
    with pytest.raises(ToolboxError,match='нет опубликованных'):
        downloads.check_update('cokker/QuestToolbox',threading.Event(),lambda _:None)


def test_directory_probe_rejects_unreadable_before_listing():
    adb=Adb('fake','device')
    calls=[]
    def denied(*args,**kwargs):
        calls.append(args)
        raise ToolboxError('Permission denied')
    adb.shell=denied
    with pytest.raises(ToolboxError): adb.list_files('/sdcard/Android/data')
    assert len(calls)==1
    assert 'test -d' in calls[0][2]


def test_official_tool_update_replaces_old_copy(monkeypatch, tmp_path):
    import io
    import quest_toolbox.downloads as downloads
    root = tmp_path / 'tools' / 'platform-tools'
    root.mkdir(parents=True)
    exe = 'adb.exe' if os.name == 'nt' else 'adb'
    (root / exe).write_bytes(b'old')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('platform-tools/' + exe, b'new')
    monkeypatch.setattr(downloads, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(downloads, 'fetch', lambda *args, **kwargs: buffer.getvalue())
    result = downloads.install_tool('adb', threading.Event(), lambda _: None)
    assert Path(result).read_bytes() == b'new'
    assert not (tmp_path / 'tools' / 'platform-tools.previous').exists()


def test_invalid_tool_archive_keeps_existing_copy(monkeypatch, tmp_path):
    import io
    import quest_toolbox.downloads as downloads
    root = tmp_path / 'tools' / 'platform-tools'
    root.mkdir(parents=True)
    exe = 'adb.exe' if os.name == 'nt' else 'adb'
    (root / exe).write_bytes(b'old')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('unrelated.txt', 'wrong archive')
    monkeypatch.setattr(downloads, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(downloads, 'fetch', lambda *args, **kwargs: buffer.getvalue())
    with pytest.raises(ToolboxError, match='не найден'):
        downloads.install_tool('adb', threading.Event(), lambda _: None)
    assert (root / exe).read_bytes() == b'old'
