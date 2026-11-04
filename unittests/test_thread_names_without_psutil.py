import threading
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import processcontrol


class ThreadNamesWithoutPsutilTest(TestCase):
    def test_active_postprocessor_is_visible_without_optional_cpu_dependency(self):
        stop = threading.Event()
        thread = threading.Thread(target=stop.wait, name="POSTPROCESS")
        thread.start()
        try:
            with patch.object(processcontrol, "PSUTIL", False):
                result = processcontrol.get_threads()
            self.assertIn(("POSTPROCESS", 0.0), result)
            self.assertTrue(all(isinstance(name, str) for name, _ in result))
        finally:
            stop.set()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
