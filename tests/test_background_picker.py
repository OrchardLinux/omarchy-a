"""Exercise picker shell requests without a compositor or a physical device."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / 'desktop/shell/bin'
QML = PROJECT / 'desktop/shell/shell/plugins/image-picker/ImagePicker.qml'


class PickerScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.images = self.root / 'images'
        self.images.mkdir()
        (self.root / 'tmp').mkdir()
        self.env = {**os.environ, 'HOME': str(self.root), 'XDG_CACHE_HOME': str(self.root / 'cache'),
                    'XDG_RUNTIME_DIR': str(self.root), 'TMPDIR': str(self.root / 'tmp'),
                    'OMARCHY_PATH': str(PROJECT / 'desktop/shell'),
                    'PATH': f'{self.bin}:/usr/bin:/bin', 'TEST_ROOT': str(self.root)}

    def script(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/python3\n' + body)
        path.chmod(0o755)

    def menu_stubs(self, result='select'):
        self.env['RESULT'] = result
        (self.images/'image.png').write_bytes(b'fixture')
        self.script('omarchy-shell', '''import os, json, sys
from pathlib import Path
args=sys.argv[1:]
if args[:2] == ['image-selector', 'open']:
    Path(os.environ['TEST_ROOT'], 'request').write_text(json.dumps(args))
    if os.environ['RESULT'] == 'reject':
        print('unknown'); sys.exit(1)
print('ok')
''')
        self.script('omarchy-picker-process', '''import os, json, sys
from pathlib import Path
root=Path(os.environ['TEST_ROOT'])
if sys.argv[1] == 'cancel':
    (root/'cancelled').write_text(sys.argv[2]); sys.exit(0)
args=json.loads((root/'request').read_text())
result=os.environ['RESULT']
if result in ('select','cancel','error'):
    if result == 'select': Path(args[5]).write_text('/background/chosen.png\\n')
    Path(args[6]).write_text('error\\n' if result == 'error' else '')
print('inactive' if result == 'lost' else 'active')
''')

    def menu(self, *args, timeout=20, lazy=True):
        return subprocess.run(['bash', str(SCRIPTS / 'omarchy-menu-images'), *(['--lazy-thumbnails'] if lazy else []), *args, str(self.images)],
                              env=self.env, capture_output=True, text=True, timeout=timeout)

    def test_selection_and_cancel_remove_request_files(self):
        for mode in ('select', 'cancel'):
            with self.subTest(mode=mode):
                self.menu_stubs(mode)
                result = self.menu()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '/background/chosen.png\n' if mode == 'select' else '')
                self.assertEqual(list((self.root/'tmp').iterdir()), [])

    def test_empty_folder_does_not_open_picker(self):
        self.menu_stubs()
        (self.images/'image.png').unlink()
        result=self.menu()
        self.assertEqual(result.returncode,1)
        self.assertIn('No images could be loaded',result.stderr)
        self.assertFalse((self.root/'request').exists())
        self.assertEqual(list((self.root/'tmp').iterdir()),[])

    def test_rejected_open_does_not_wait(self):
        self.menu_stubs('reject')
        result = self.menu()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to accept', result.stderr)
        self.assertEqual(list((self.root/'tmp').iterdir()), [])

    def test_helper_failure_is_not_reported_as_cancel(self):
        self.menu_stubs('error')
        result = self.menu()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Image selector failed', result.stderr)
        self.assertEqual(list((self.root/'tmp').iterdir()), [])

    def test_accepted_but_lost_request_has_bounded_wait(self):
        self.menu_stubs('lost')
        result = self.menu(timeout=18)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stopped responding', result.stderr)
        self.assertTrue((self.root/'cancelled').exists())
        self.assertEqual(list((self.root/'tmp').iterdir()), [])

    def test_terminated_caller_cancels_only_its_request(self):
        self.menu_stubs('wait')
        process = subprocess.Popen(['bash', str(SCRIPTS/'omarchy-menu-images'), '--lazy-thumbnails', str(self.images)],
                                   env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if (self.root/'request').exists(): break
                time.sleep(.02)
            self.assertTrue((self.root/'request').exists())
            args=json.loads((self.root/'request').read_text())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertEqual((self.root/'cancelled').read_text(), args[6])
            self.assertEqual(list((self.root/'tmp').iterdir()), [])
        finally:
            if process.poll() is None: process.kill(); process.wait()

    def test_cold_thumbnail_cache_and_failed_converter(self):
        self.menu_stubs()
        (self.images/'image.png').write_bytes(b'fixture')
        self.script('vipsthumbnail', '''import sys
from pathlib import Path
Path(sys.argv[-1].split('[',1)[0]).write_bytes(b'thumbnail')
''')
        result=self.menu('--print-rows', lazy=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('image.png\t', result.stdout)
        shutil.rmtree(self.root/'cache')
        self.script('vipsthumbnail', 'import sys; sys.exit(1)\n')
        result=self.menu('--print-rows', lazy=False)
        self.assertEqual(result.stdout.strip(), '')
        self.script('vipsthumbnail', '''import sys
from pathlib import Path
Path(sys.argv[-1].split('[',1)[0]).write_bytes(b'thumbnail')
''')
        self.assertIn('image.png\t', self.menu('--print-rows', lazy=False).stdout)

    def helper_stubs(self, child=None):
        self.script('qs', '''import os, sys, json, time
from pathlib import Path
root=Path(os.environ['TEST_ROOT'])
if sys.argv[1] == '-p':
    (root/'picker-pid').write_text(str(os.getpid()))
    if os.environ.get('CHILD') == 'crash': sys.exit(1)
    (root/'ready').touch()
    time.sleep(30)
else:
    action=sys.argv[sys.argv.index('picker')+1]
    if action == 'ping':
        if not (root/'ready').exists(): sys.exit(1)
        print('ok')
    elif action == 'open': print('ok')
    elif action == 'cancel': (root/'cancelled').write_text(sys.argv[-1])
''')
        self.script('pgrep', '''import os
from pathlib import Path
print(Path(os.environ['TEST_ROOT'], 'picker-pid').read_text())
''')
        if child: self.env['CHILD'] = child

    def start_helper(self):
        selection, done = self.root/'selection', self.root/'done'
        selection.touch()
        payload=json.dumps({'selectionFile':str(selection), 'doneFile':str(done)})
        process=subprocess.Popen(['bash', str(SCRIPTS/'omarchy-picker-process'), 'open', payload],
                                 env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, process)
        return process, selection, done

    @staticmethod
    def stop(process):
        if process.poll() is None: process.terminate()
        process.wait(timeout=5)

    def test_reused_picker_helper_finishes_with_request_not_process(self):
        self.helper_stubs()
        picker=subprocess.Popen(['sleep','30'])
        self.addCleanup(self.stop, picker)
        (self.root/'picker-pid').write_text(str(picker.pid))
        (self.root/'ready').touch()
        helper, selection, done=self.start_helper()
        time.sleep(.3)
        done.touch()  # selection, cancellation and replacement all signal done
        self.assertEqual(helper.wait(timeout=3),0)
        self.assertIsNone(picker.poll())

    def test_picker_crash_releases_waiter(self):
        self.helper_stubs('crash')
        helper, selection, done=self.start_helper()
        self.assertEqual(helper.wait(timeout=5),1)
        self.assertEqual(done.read_text(), 'error\n')
        self.assertEqual(list(self.root.glob('omarchy-picker-request.*')), [])

    def test_new_picker_helper_stops_after_caller_disappears(self):
        self.helper_stubs()
        helper, selection, done=self.start_helper()
        try:
            for _ in range(100):
                if (self.root/'ready').exists(): break
                time.sleep(.02)
            selection.unlink()
            self.assertEqual(helper.wait(timeout=4),0)
            self.assertEqual((self.root/'cancelled').read_text(),str(done))
            self.assertFalse(done.exists())
            self.assertEqual(list(self.root.glob('omarchy-picker-request.*')), [])
        finally:
            pid_file=self.root/'picker-pid'
            if pid_file.exists():
                try: os.kill(int(pid_file.read_text()), signal.SIGTERM)
                except ProcessLookupError: pass

    def test_thumbnail_dependencies_are_packaged(self):
        packages=(PROJECT/'system/packages.txt').read_text().splitlines()
        self.assertIn('diffutils', packages)
        self.assertIn('libvips', packages)
        self.assertIn('ffmpegthumbnailer', packages)


@unittest.skipUnless(shutil.which('node'), 'Node is needed to execute the QML JavaScript functions')
class PickerQml(unittest.TestCase):
    def function(self, name):
        source=QML.read_text()
        start=source.index('  function '+name+'(')
        opening=source.index('{',start)
        depth=1
        end=opening+1
        while depth:
            depth += (source[end]=='{') - (source[end]=='}')
            end+=1
        return source[start:end]

    def test_empty_rows_cancel_and_stale_cancel_is_ignored(self):
        functions='\n'.join(self.function(n) for n in ('loadRows','closeSelector'))
        script="""const vm=require('vm'), assert=require('assert');
const ctx={requestActive:true, requestSerial:1, doneFile:'/done', opened:true,
 ImagePickerModel:{loadRows:()=>[]}, cancel:()=>{ctx.cancelled=true},
 finishDoneFile:p=>{ctx.released=p}};
ctx.root=ctx;
vm.createContext(ctx);
""" + 'vm.runInContext('+json.dumps(functions)+',ctx);\n' + """
ctx.loadRows('',true);
assert.equal(ctx.cancelled,true);
const serial=ctx.requestSerial;
assert.equal(ctx.closeSelector('/older-done'),false);
assert.equal(ctx.opened,true);
assert.equal(ctx.requestSerial,serial);
assert.equal(ctx.closeSelector('/done'),true);
assert.equal(ctx.opened,false);
assert.equal(ctx.released,'/done');
"""
        subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


if __name__ == '__main__':
    unittest.main()
