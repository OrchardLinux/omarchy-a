#!/usr/bin/env python3
"""Read-only battery and system telemetry with bounded SQLite history."""
import json
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from system_telemetry import COLUMNS, CHART_FIELDS, SystemCollector, public_current, aggregate, summarize

ROOT = Path(__file__).parent
POWER = Path(os.environ.get('BATTERY_POWER_PATH', '/sys/class/power_supply'))
DATABASE = Path(os.environ.get('BATTERY_DATABASE', '/var/lib/ipad-battery-monitor/history.sqlite3'))
STOP = threading.Event()
FIELDS = {'capacity': ('battery', 'capacity'), 'status': ('battery', 'status'),
          'current_uA': ('battery', 'current_now'), 'voltage_uV': ('battery', 'voltage_now'),
          'temperature_deciC': ('battery', 'temp'), 'health': ('battery', 'health'),
          'online': ('lightning', 'online'), 'usb_type': ('lightning', 'usb_type'),
          'input_limit_uA': ('lightning', 'input_current_limit')}
TEXT = {'status', 'health', 'usb_type'}
HISTORY_LOCK=threading.Lock()
CURRENT_LOCK=threading.Lock()
HISTORY_CACHE={}
CURRENT_CACHE={'at':0}
CURRENT_COLLECTOR=SystemCollector()


def snapshot():
    result = {'timestamp': int(time.time())}
    for key, (supply, name) in FIELDS.items():
        try:
            value = (POWER / supply / name).read_text().strip()
            result[key] = value[:100] if key in TEXT else int(value)
        except (OSError, ValueError):
            result[key] = None
    return result


@contextmanager
def connection():
    db=sqlite3.connect(DATABASE,timeout=2)
    try:
        with db:yield db
    finally:db.close()


def initialize():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS samples (timestamp INTEGER PRIMARY KEY, capacity INTEGER, current_uA INTEGER, temperature_deciC INTEGER, input_limit_uA INTEGER, status TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS system_samples ('+', '.join(k+' '+v for k,v in COLUMNS.items())+')')


def record(row,system=None,db=None):
    if db is None:
        with connection() as own:return record(row,system,own)
    with db:
        db.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?)',
                   tuple(row[k] for k in ('timestamp', 'capacity', 'current_uA', 'temperature_deciC', 'input_limit_uA', 'status')))
        db.execute('DELETE FROM samples WHERE timestamp < ?', (row['timestamp'] - 7 * 86400,))
        if system is not None:
            db.execute('INSERT OR REPLACE INTO system_samples VALUES ('+','.join('?' for _ in COLUMNS)+')',tuple(system[k] for k in COLUMNS))
            db.execute('DELETE FROM system_samples WHERE timestamp < ?', (row['timestamp']-86400,))
    with HISTORY_LOCK:HISTORY_CACHE.clear()


def history(hours):
    with connection() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM samples WHERE timestamp >= ? ORDER BY timestamp',
                          (int(time.time()) - hours * 3600,)).fetchall()
    return [dict(row) for row in rows]

def system_history(hours):
    with connection() as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM system_samples WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp',
                (int(time.time())-hours*3600,int(time.time())))]

def current_payload():
    with CURRENT_LOCK:
        if 'battery' not in CURRENT_CACHE or time.monotonic()-CURRENT_CACHE['at']>=5:
            CURRENT_CACHE.update(at=time.monotonic(),battery=snapshot(),system=public_current(CURRENT_COLLECTOR.collect()))
        return {'current':CURRENT_CACHE['battery'],'system':{'current':CURRENT_CACHE['system']},'sample_interval_seconds':60,'read_only':True}

def history_payload(hours):
    with HISTORY_LOCK:
        cached=HISTORY_CACHE.get(hours)
        if cached and time.monotonic()-cached['at']<60:return cached['data']
        seconds=max(60,hours*3600//360)
        rows=system_history(hours)
        data={'history':aggregate(history(hours),('capacity','current_uA','temperature_deciC','input_limit_uA'),seconds),
              'system_history':aggregate(rows,CHART_FIELDS,seconds),'summary':summarize(rows),'display_interval_seconds':seconds,
              'window_start':int(time.time())-hours*3600,'window_end':int(time.time())}
        HISTORY_CACHE[hours]={'at':time.monotonic(),'data':data}
        return data


def sample_loop():
    collector=SystemCollector()
    while not STOP.is_set():
        try:
            with connection() as db:
                while not STOP.is_set():
                    record(snapshot(),collector.collect(),db)
                    STOP.wait(60)
        except (OSError, sqlite3.Error):
            logging.exception('Unable to save telemetry sample')
            STOP.wait(60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in ('/', '/zh-CN'):
            page = 'index.zh-CN.html' if parsed.path == '/zh-CN' else 'index.html'
            return self.respond(200, (ROOT / page).read_bytes(), 'text/html; charset=utf-8')
        if parsed.path == '/favicon.ico':
            return self.respond(204, b'', 'image/x-icon')
        if parsed.path == '/health':
            return self.respond(200, b'{"ok":true}', 'application/json')
        if parsed.path != '/api/battery':
            return self.respond(404, b'Not found', 'text/plain')
        try:
            query=parse_qs(parsed.query,max_num_fields=2)
            hours = int(query.get('hours', ['24'])[0])
            view=query.get('view',['history'])[0]
            if hours not in (1, 6, 24) or view not in ('current','history') or set(query)-{'hours','view'}:
                raise ValueError()
        except (ValueError, IndexError):
            return self.respond(400, b'Invalid hours', 'text/plain')
        try:
            data = current_payload()
            if view=='history':
                h=history_payload(hours)
                data.update(history=h['history'],system={'current':data['system']['current'],'history':h['system_history'],'summary':h['summary']},
                    display_interval_seconds=h['display_interval_seconds'],window_start=h['window_start'],window_end=h['window_end'])
            data.update(retention_days=7,system_retention_hours=24,timezone='browser-local')
            self.respond(200, json.dumps(data, separators=(',', ':')).encode(), 'application/json; charset=utf-8')
        except (OSError, sqlite3.Error):
            self.respond(503, b'{"error":"telemetry unavailable"}', 'application/json')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self,*args):
        self.slots=threading.BoundedSemaphore(8)
        super().__init__(*args)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):request.close();return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(5)
        return sock, addr


def main():
    os.umask(0o077)
    initialize()
    current_payload()
    worker = threading.Thread(target=sample_loop, daemon=True)
    worker.start()
    server = Server((os.environ.get('BATTERY_BIND', '127.0.0.1'), int(os.environ.get('BATTERY_PORT', '3001'))), Handler)
    server.timeout = 1
    def stop(*_args):
        STOP.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.warning('Read-only battery monitor listening on port %s', server.server_port)
    try:
        while not STOP.is_set():
            server.handle_request()
    finally:
        server.server_close()
        worker.join(timeout=3)


if __name__ == '__main__':
    main()
