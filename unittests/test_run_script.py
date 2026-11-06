import concurrent.futures
import os
import sys
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian.common import run_script


class RunScriptTest(TestCase):
    def test_threaded_commands_preserve_arguments_streams_and_exit_status(self):
        script = 'import sys; print(sys.argv[1]); print("diagnostic", file=sys.stderr); sys.exit(7)'
        params = [sys.executable, '-c', script, 'a b; $(literal)']
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: run_script(params), range(12)))
        for rc, out, err in results:
            self.assertEqual(rc, 7)
            self.assertEqual(out.strip(), 'a b; $(literal)')
            self.assertEqual(err.strip(), 'diagnostic')
        self.assertEqual(len(params), 4)

    def test_unix_priority_applies_only_to_child(self):
        if os.name == 'nt':
            self.skipTest('Unix priority only')
        priority = os.nice(0)
        rc, out, _ = run_script([sys.executable, '-c', 'import os; print(os.nice(0))'])
        self.assertEqual(rc, 0)
        self.assertEqual(int(out), min(priority + 10, 19))
        self.assertEqual(os.nice(0), priority)

    def test_no_nice_binary_still_runs_command(self):
        with patch('lazylibrarian.common.shutil.which', return_value=None):
            rc, out, _ = run_script([sys.executable, '-c', 'print("ok")'])
        self.assertEqual((rc, out.strip()), (0, 'ok'))

    def test_no_python_callback_before_exec(self):
        with patch('lazylibrarian.common.subprocess.Popen') as popen:
            popen.return_value.communicate.return_value = (b'', b'')
            popen.return_value.returncode = 0
            run_script(['/bin/true'])
        self.assertNotIn('preexec_fn', popen.call_args.kwargs)
