"""Desktop entry point, including a visible report if bundled imports fail."""
import sys
import traceback
if __name__ == '__main__':
    try:
        from quest_toolbox.ui import main
        sys.exit(main())
    except Exception:
        error = traceback.format_exc()
        if '--smoke-test' in sys.argv:
            from pathlib import Path
            import json
            index=sys.argv.index('--smoke-test')
            if index+1<len(sys.argv):
                target=Path(sys.argv[index+1]); target.mkdir(parents=True,exist_ok=True)
                (target/'smoke-result.json').write_text(json.dumps({'ok':False,'error':error}), 'utf-8')
        elif sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, error, 'Quest Toolbox — startup error', 0x10)
        else:
            print(error, file=sys.stderr)
        sys.exit(1)
