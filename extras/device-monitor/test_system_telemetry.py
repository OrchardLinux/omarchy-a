import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import system_telemetry as s

class SystemTests(unittest.TestCase):
    def test_signed_battery_sensors_and_legacy_history_migration(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ):
            root = Path(td)
            power = root / 'power/battery'
            power.mkdir(parents=True)
            for name, value in {'current_now': '-86000', 'capacity': '94', 'temp': '259'}.items():
                (power / name).write_text(value)
            os.environ['BATTERY_DATABASE'] = str(root / 'history.sqlite3')
            os.environ['BATTERY_POWER_PATH'] = str(root / 'power')
            spec = importlib.util.spec_from_file_location(
                'battery_fixture', Path(__file__).with_name('battery-monitor.py'))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            now = int(time.time())
            with m.connection() as db:
                db.execute('CREATE TABLE samples (timestamp INTEGER PRIMARY KEY, capacity INTEGER, current_uA INTEGER, temperature_deciC INTEGER, input_limit_uA INTEGER, status TEXT)')
                db.execute('INSERT INTO samples VALUES (?,50,-10,250,NULL,NULL)', (now - 60,))
                db.execute('INSERT INTO samples VALUES (?,50,-10,250,NULL,NULL)', (now - 8 * 86400,))
            m.initialize()
            with m.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0], 2)
            row = m.snapshot()
            self.assertEqual(row['current_uA'], -86000)
            self.assertEqual(row['temperature_deciC'], 259)
            self.assertIsNone(row['status'])
            m.record(row)
            with m.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0], 2)
            (power / 'current_now').unlink()
            self.assertIsNone(m.snapshot()['current_uA'])

    def test_proc_counters_units_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);proc=root/'proc';sys=root/'sys'
            def write(p,text):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            write(proc/'stat','cpu 100 0 100 800 0 0 0 0 60 0\n')
            write(proc/'meminfo','MemTotal: 2000 kB\nMemAvailable: 1000 kB\nSwapTotal: 100 kB\nSwapFree: 80 kB\n')
            write(proc/'loadavg','0.1 0.2 0.3 1/2 3');write(proc/'uptime','100 180')
            write(proc/'sys/kernel/random/boot_id','boot-one')
            write(sys/'class/net/wld0/operstate','up');(sys/'class/net/wld0/device').mkdir()
            write(proc/'net/dev','header\nheader\nwld0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\nlo: 999999 0 0 0 0 0 0 0 999999 0\n')
            dev=os.stat('/').st_dev;block=sys/'dev/block'/f'{os.major(dev)}:{os.minor(dev)}'/'stat';write(block,'0 0 10 0 0 0 20 0 0 0 0')
            collector=s.SystemCollector(proc,sys)
            with patch.object(s.time,'monotonic',return_value=10):first=collector.collect()
            self.assertIsNone(first['cpu_percent']);self.assertEqual(first['mem_used_bytes'],1024000)
            self.assertEqual(first['swap_used_bytes'],20480);self.assertEqual(first['disk_read_bytes'],5120)
            write(proc/'stat','cpu 150 0 150 900 0 0 0 0 99 0\n');write(proc/'net/dev','header\nheader\nwld0: 1100 0 0 0 0 0 0 0 2200 0 0 0 0 0 0 0\n')
            with patch.object(s.time,'monotonic',return_value=20):second=collector.collect()
            self.assertEqual(second['cpu_percent'],50);self.assertEqual(second['net_rx_Bps'],100)
            self.assertEqual(second['net_tx_Bps'],200)
            write(proc/'sys/kernel/random/boot_id','boot-two')
            with patch.object(s.time,'monotonic',return_value=30):third=collector.collect()
            self.assertIsNone(third['cpu_percent']);self.assertIsNone(third['net_rx_Bps'])
            self.assertNotIn('boot_id',s.public_current(third))
            self.assertIsNone(s.rate(10,100,10));self.assertIsNone(s.rate(100,10,0))

    def test_aggregation_preserves_peak_and_reboot_gaps(self):
        rows=[{'timestamp':i*60,'cpu_percent':v,'mem_used_bytes':100+i,'boot_id':'a','network_key':'wld0'} for i,v in enumerate([0,100,0,0,50])]
        points=s.aggregate(rows,('cpu_percent',),240)
        self.assertEqual(points[0]['cpu_percent'],25);self.assertEqual(points[0]['cpu_peak'],100)
        self.assertEqual(s.summarize(rows)['cpu_peak_percent'],100)
        rows[2]['boot_id']='b'
        self.assertTrue(any(p['break_before'] for p in s.aggregate(rows,('cpu_percent',),240)))

    def test_totals_exclude_counter_reset_reboot_and_missing_intervals(self):
        rows=[]
        for timestamp,boot,value in [(100,'a',100),(160,'a',200),(220,'b',10),(280,'b',40),(600,'b',100)]:
            rows.append({'timestamp':timestamp,'boot_id':boot,'network_key':'wld0','net_rx_bytes':value,'net_tx_bytes':value,'disk_read_bytes':value,'disk_write_bytes':value})
        summary=s.summarize(rows)
        self.assertEqual(summary['network_rx_bytes'],130);self.assertEqual(summary['disk_write_bytes'],130)
        self.assertEqual(summary['network_coverage_seconds'],120)
        self.assertIsNone(s.summarize(rows[:1])['network_rx_bytes'])

    def test_additive_storage_retention_and_lightweight_api(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ):
            root=Path(td);os.environ['BATTERY_DATABASE']=str(root/'history.sqlite3');os.environ['BATTERY_POWER_PATH']=str(root/'power')
            spec=importlib.util.spec_from_file_location('monitor_fixture',Path(__file__).with_name('battery-monitor.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            m.initialize();now=int(time.time());old=now-25*3600
            battery={k:None for k in m.FIELDS};battery['timestamp']=old;battery['capacity']=50
            system={k:None for k in s.COLUMNS};system.update(timestamp=old,boot_id='old-boot')
            m.record(battery,system);m.record({**battery,'timestamp':now},{**system,'timestamp':now})
            with m.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM system_samples').fetchone()[0],1)
            self.assertEqual(len(m.history(1)),1)
            with m.connection() as writer:
                m.record({**battery,'timestamp':now-1},{**system,'timestamp':now-1},writer)
                with m.connection() as reader:
                    self.assertEqual(reader.execute('SELECT count(*) FROM system_samples WHERE timestamp=?',(now-1,)).fetchone()[0],1)
            server=m.Server(('127.0.0.1',0),m.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            original=m.history_payload;m.history_payload=lambda *_:self.fail('Current refresh must not load history')
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/battery?view=current') as r:d=json.load(r)
                self.assertNotIn('history',d);self.assertIn('current',d['system'])
                for route, language in [('/', 'en'), ('/zh-CN', 'zh-CN')]:
                    with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+route) as r:
                        self.assertIn('lang="'+language+'"', r.read().decode())
                for query in ('hours=2', 'view=unknown', 'extra=1'):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/battery?'+query)
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
            finally:m.history_payload=original;server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
