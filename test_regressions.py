"""Windows regression tests. Mock input injection; never type into user apps."""
import copy
import ctypes
import importlib.util
import queue
import threading
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

SOURCE = Path(__file__).with_name('main.py')
spec = importlib.util.spec_from_file_location('recorder', SOURCE)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(app.RawInputMouseCapture, 'start', return_value=True),
            patch.object(app.InputEngine, '_hook_loop', lambda s: s.hook_ready.set()),
            patch.object(app.user32, 'GetAsyncKeyState', return_value=0),
            patch.object(app.user32, 'CallNextHookEx', return_value=0),
        ]
        for p in self.patches:
            p.start()
        self.engine = app.InputEngine(queue.Queue())
        self.engine.mouse_guard = Mock()

    def tearDown(self):
        self.engine.recording = False
        if self.engine.record_timer:
            self.engine.record_timer.timeEndPeriod(1)
            self.engine.record_timer = None
        for p in reversed(self.patches):
            p.stop()

    def record(self, mode='gfn_raw'):
        self.engine.start_recording(mode)

    def finish(self, elapsed=2.0):
        with patch.object(self.engine, 'elapsed_record_time', return_value=elapsed):
            return self.engine.stop_recording_and_trim()

    def keyboard(self, vk, scan, down=True, dt=10, flags=0):
        data = app.KBDLLHOOKSTRUCT(vk, scan, flags,
                                  (self.engine.record_tick + dt) & 0xFFFFFFFF, 0)
        with patch.object(app.time, "perf_counter_ns", return_value=self.engine.record_start_ns+dt*1_000_000):
            self.engine._keyboard_proc(0, app.WM_KEYDOWN if down else app.WM_KEYUP, ctypes.addressof(data))

    def test_1000hz_stroke_keeps_all_packets_and_times(self):
        self.record()
        expected = []
        for i in range(1000):
            dx, dy = (i % 9) - 4, (i % 7) - 3
            expected.append((dx, dy))
            self.engine.on_raw_delta(dx, dy, 960, 540, timestamp_ns=self.engine.record_start_ns+i*1_000_000)
        result = self.finish()
        moves = [e for e in result['events'] if e['type'] == 'relative_move']
        self.assertEqual(len(moves), 1000)
        self.assertEqual([(e['dx'], e['dy']) for e in moves], expected)
        self.assertEqual([e['t'] for e in moves], [i/1000 for i in range(1000)])
        self.assertEqual(result['meta']['raw_dx_total'], sum(x for x, y in expected))
        self.assertEqual(result['meta']['raw_dy_total'], sum(y for x, y in expected))
        self.assertEqual(result['events'][-1]['t'], 2.0)

    def test_sparse_slow_moves_are_not_discarded(self):
        self.record()
        for dt in (1, 200, 800, 1400):
            self.engine.on_raw_delta(1, -1, 960, 540, timestamp_ns=self.engine.record_start_ns+dt*1_000_000)
        result = self.finish()
        self.assertEqual(result['meta']['pointer_lock_samples'], 4)

    def test_raw_clicks_do_not_have_absolute_positions(self):
        self.record()
        self.engine._record_event({'type':'mouse_button', 'button':'left', 'down':True,
                                    'x':960, 'y':540})
        result = self.finish()
        click = result['events'][0]
        self.assertTrue(click['relative_mouse_mode'])
        self.assertNotIn('x', click)
        self.assertNotIn('nx', click)
        with patch.object(self.engine, '_set_cursor_for_event', side_effect=AssertionError('warp')), patch.object(app, 'send_mouse') as send:
            self.engine._execute_event(click)
            send.assert_called_once_with(app.MOUSEEVENTF_LEFTDOWN, data=0)

    def test_keyboard_chord_autorepeat_and_release_order(self):
        self.record()
        self.keyboard(0xA0, 0x2A, dt=1)
        self.keyboard(0x57, 0x11, dt=2)
        self.keyboard(0x57, 0x11, dt=3)
        self.keyboard(0x57, 0x11, down=False, dt=4)
        self.keyboard(0xA0, 0x2A, down=False, dt=5)
        result = self.finish()
        events = [e for e in result['events'] if e['type']=='key']
        self.assertEqual([(e['vk'],e['down']) for e in events],
                         [(0xA0,True),(0x57,True),(0x57,True),(0x57,False),(0xA0,False)])
        with patch.object(app, 'send_key') as send:
            for e in events:
                self.engine._execute_event(e)
            self.assertEqual(send.call_count, 5)
        self.assertFalse(self.engine.playback_pressed_keys)

    def test_hotkeys_excluded_and_f9_interrupts_immediately(self):
        self.record()
        self.keyboard(app.VK_F8, 0x42)
        self.engine.playing = True
        self.keyboard(app.VK_F9, 0x43)
        self.assertTrue(self.engine.play_stop.is_set())
        self.assertEqual(self.engine.events, [])

    def test_same_timestamp_keeps_original_event_order(self):
        self.record()
        self.keyboard(0x57, 0x11, dt=10)
        self.engine.on_raw_delta(2, 3, 960, 540, timestamp_ns=self.engine.record_start_ns+10_000_000)
        self.keyboard(0x57, 0x11, down=False, dt=10)
        result = self.finish()
        self.assertEqual([e['type'] for e in result['events'][:3]], ['key','relative_move','key'])

    def test_cursor_viewport_maps_on_negative_monitor(self):
        self.record('cursor')
        self.engine.record_rect = (-1920, 0, 0, 1080)
        self.engine._record_event({'type':'move','x':-961,'y':540})
        result = self.finish()
        event = result['events'][0]
        self.assertEqual(app.position_in_rect(event['nx'],event['ny'],self.engine.record_rect),(-961,540))
        self.engine.playback_rect = (100,100,2020,1180)
        with patch.object(self.engine, '_set_cursor') as move:
            self.engine._set_cursor_for_event(event)
            move.assert_called_once_with(1059,640)

    def test_recording_duration_and_opt_in_trim(self):
        self.record()
        self.engine._record_event({'type':'key','vk':87,'scan':17,'extended':False,'down':True},timestamp_ns=self.engine.record_start_ns+500_000_000)
        self.engine._record_event({'type':'key','vk':87,'scan':17,'extended':False,'down':False},timestamp_ns=self.engine.record_start_ns+6_500_000_000)
        result=self.finish(7.0)
        self.assertEqual(result['meta']['recorded_seconds'],7.0)
        self.assertEqual(len(result['events']),3)
        self.record()
        self.engine.trim_seconds=5.0
        self.engine._record_event({'type':'relative_move','dx':2,'dy':3},timestamp_ns=self.engine.record_start_ns+500_000_000)
        self.engine._record_event({'type':'relative_move','dx':5,'dy':9},timestamp_ns=self.engine.record_start_ns+6_500_000_000)
        result=self.finish(7.0)
        self.assertEqual(result['meta']['recorded_seconds'],2.0)
        self.assertEqual(len(result['events']),2)

    def test_three_loops_release_held_chord_and_mouse_at_each_boundary(self):
        self.record()
        for vk, scan in ((0x57,17),(0xA0,42)):
            self.engine._record_event({'type':'key','vk':vk,'scan':scan,'extended':False,'down':True})
        self.engine._record_event({'type':'mouse_button','button':'right','down':True,'x':500,'y':300})
        result=self.finish(0.1)
        events,duration=app.validate_macro(result)
        e=self.engine
        e.playback_macro=result
        e.playing=True
        releases=0
        original=e._release_all_inputs
        def release():
            nonlocal releases
            original()
            releases+=1
            if releases==3:
                e.play_stop.set()
        with patch.object(app,'send_key') as keys, patch.object(app,'send_mouse') as mouse, patch.object(e,'_target_active',return_value=True), patch.object(e,'_wait_until',return_value=True), patch.object(e,'_release_all_inputs',side_effect=release):
            e._play_worker(events,duration)
            self.assertEqual(e.completed_loops,3)
            self.assertEqual(keys.call_count,12)
            self.assertEqual(mouse.call_count,6)
        self.assertFalse(e.playback_pressed_keys)
        self.assertFalse(e.playback_pressed_mouse)
        self.assertFalse(e.playing)

    def test_stop_interrupts_long_wait(self):
        self.engine.playback_hwnd=None
        worker=threading.Thread(target=lambda:self.engine._wait_until(time.monotonic()+60))
        worker.start()
        begin=time.monotonic()
        self.engine.stop_playback()
        worker.join(0.25)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic()-begin,0.25)

    def test_focus_loss_aborts_and_releases(self):
        self.engine.playback_macro={'meta':{'mouse_mode':'gfn_raw'}}
        with patch.object(self.engine,'_target_active',return_value=False), patch.object(self.engine,'_release_all_inputs') as release:
            self.engine._play_worker([{'type':'idle_wait','t':0.1}],0.1)
            release.assert_called_once()
        self.assertIn('focus',self.engine.last_playback_error)

    def test_win32_struct_sizes_and_sendinput_encoding(self):
        self.assertEqual(ctypes.sizeof(app.INPUT),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)
        captured=[]
        def send(count,ptr,size):
            packet=ctypes.cast(ptr,ctypes.POINTER(app.INPUT)).contents
            captured.append((packet.type,packet.mi.dx,packet.mi.dy,packet.mi.dwFlags,packet.ki.wVk,packet.ki.wScan,packet.ki.dwFlags))
            return 1
        with patch.object(app.user32,'SendInput',side_effect=send):
            app.send_mouse(app.MOUSEEVENTF_MOVE,-17,23)
            app.send_key(0x57,17,False,True)
            app.send_key(0xA3,29,True,False)
        self.assertEqual(captured[0][1:4],(-17,23,app.MOUSEEVENTF_MOVE))
        self.assertEqual(captured[1][4:],(0,17,app.KEYEVENTF_SCANCODE))
        self.assertEqual(captured[2][6],app.KEYEVENTF_SCANCODE|app.KEYEVENTF_EXTENDEDKEY|app.KEYEVENTF_KEYUP)

    def test_malformed_and_old_macro_rejected_before_injection(self):
        self.record()
        self.engine.on_raw_delta(1,2,960,540)
        result=self.finish()
        for invalid in (float('nan'),float('inf'),-1):
            bad=copy.deepcopy(result)
            bad['events'][0]['t']=invalid
            self.assertFalse(self.engine.start_playback(bad)[0])
        result['meta']['format_version']=2
        self.assertIn('record again',self.engine.start_playback(result)[1])

    def test_8000hz_qpc_timestamps_do_not_use_coarse_windows_ticks(self):
        self.record()
        for i in range(80):
            self.engine.on_raw_delta(1,-1,500,300,tick=self.engine.record_tick,
                                      timestamp_ns=self.engine.record_start_ns+i*125_000)
        result=self.finish(0.1)
        moves=result['events'][:-1]
        self.assertEqual(len(moves),80)
        for i,event in enumerate(moves):
            self.assertAlmostEqual(event['t'],i*0.000125,places=12)
        self.assertEqual(result['meta']['timestamp_clock'],'perf_counter_ns')
        self.assertEqual(result['meta']['format_version'],3)

    def test_f8_uses_qpc_and_excludes_input_after_stop(self):
        self.record()
        self.engine.on_raw_delta(2,3,500,300,timestamp_ns=self.engine.record_start_ns+1_000_000)
        self.keyboard(app.VK_F8,0x42,dt=40)
        self.engine.on_raw_delta(9,10,500,300,timestamp_ns=self.engine.record_start_ns+60_000_000)
        result=self.finish(3.0)
        self.assertEqual(result['meta']['recorded_seconds'],0.04)
        self.assertEqual(result['meta']['raw_dx_total'],2)
        self.assertEqual(result['meta']['pointer_lock_samples'],1)

    def test_mouse_guard_restores_original_settings_and_removes_journal(self):
        original={'threshold1':6,'threshold2':10,'acceleration':1,'speed':10}
        with tempfile.TemporaryDirectory() as d, patch.object(app,'APP_DATA_DIR',Path(d)), patch.object(app,'mouse_settings',side_effect=[original,app.NEUTRAL_MOUSE]), patch.object(app,'apply_mouse_settings') as apply, patch.object(app.subprocess,'Popen'):
            guard=app.MouseInputGuard()
            guard.acquire()
            self.assertTrue(guard.journal.exists())
            guard.release()
            self.assertFalse(guard.journal.exists())
            self.assertEqual([call.args[0] for call in apply.call_args_list],[app.NEUTRAL_MOUSE,original])

    def test_mouse_guard_rollback_if_normalization_fails(self):
        original={'threshold1':6,'threshold2':10,'acceleration':1,'speed':12}
        with tempfile.TemporaryDirectory() as d, patch.object(app,'APP_DATA_DIR',Path(d)), patch.object(app,'mouse_settings',return_value=original), patch.object(app,'apply_mouse_settings',side_effect=[OSError('failed'),None]) as apply, patch.object(app.subprocess,'Popen'):
            guard=app.MouseInputGuard()
            with self.assertRaises(OSError):guard.acquire()
            self.assertIsNone(guard.original)
            self.assertFalse(guard.journal.exists())
            self.assertEqual(apply.call_args_list[-1].args[0],original)

    def test_mouse_guard_respects_manual_setting_change(self):
        original={'threshold1':6,'threshold2':10,'acceleration':1,'speed':10}
        manual={**original,'speed':12}
        with tempfile.TemporaryDirectory() as d, patch.object(app,'APP_DATA_DIR',Path(d)), patch.object(app,'mouse_settings',side_effect=[original,manual]), patch.object(app,'apply_mouse_settings') as apply, patch.object(app.subprocess,'Popen'):
            guard=app.MouseInputGuard();guard.acquire();guard.release()
            apply.assert_called_once_with(app.NEUTRAL_MOUSE)

    def test_watchdog_journal_restores_and_deletes(self):
        original={'threshold1':6,'threshold2':10,'acceleration':1,'speed':10}
        with tempfile.TemporaryDirectory() as d, patch.object(app,'mouse_settings',return_value=app.NEUTRAL_MOUSE), patch.object(app,'apply_mouse_settings') as apply:
            path=Path(d)/'restore.json'
            path.write_text(app.json.dumps({'original':original}),encoding='utf-8')
            app.restore_mouse_journal(path)
            apply.assert_called_once_with(original)
            self.assertFalse(path.exists())

    def test_native_waitable_timer_can_be_cancelled(self):
        waiter=app.PrecisePlaybackWaiter()
        stop=threading.Event()
        result=[]
        try:
            thread=threading.Thread(target=lambda:result.append(waiter.wait_until(time.monotonic()+30,stop,lambda:True)))
            thread.start()
            start=time.monotonic()
            stop.set();waiter.cancel();thread.join(0.1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result,[False])
            self.assertLess(time.monotonic()-start,0.1)
        finally:waiter.close()

    def test_capture_error_restores_guard_and_timer(self):
        with patch.object(app.user32,'GetAsyncKeyState',side_effect=OSError('simulated capture error')):
            with self.assertRaises(OSError):self.record()
        self.engine.mouse_guard.release.assert_called_once()
        self.assertIsNone(self.engine.record_timer)
        self.assertFalse(self.engine.recording)


if __name__=='__main__':
    unittest.main(verbosity=2)
