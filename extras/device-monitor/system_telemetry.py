"""Passive machine counters; no process lists, addresses, packets or active probes."""
import math
import os
from pathlib import Path
import time

COLUMNS={'timestamp':'INTEGER PRIMARY KEY','cpu_percent':'REAL','load_1':'REAL','load_5':'REAL',
 'mem_total_bytes':'INTEGER','mem_available_bytes':'INTEGER','mem_used_bytes':'INTEGER',
 'swap_total_bytes':'INTEGER','swap_used_bytes':'INTEGER','disk_total_bytes':'INTEGER',
 'disk_used_bytes':'INTEGER','disk_available_bytes':'INTEGER','net_rx_Bps':'REAL','net_tx_Bps':'REAL',
 'disk_read_Bps':'REAL','disk_write_Bps':'REAL','uptime_seconds':'REAL','net_rx_bytes':'INTEGER',
 'net_tx_bytes':'INTEGER','disk_read_bytes':'INTEGER','disk_write_bytes':'INTEGER',
 'boot_id':'TEXT','network_key':'TEXT'}
CHART_FIELDS=('cpu_percent','load_1','load_5','mem_used_bytes','swap_used_bytes','disk_used_bytes',
              'net_rx_Bps','net_tx_Bps','disk_read_Bps','disk_write_Bps')

def rate(current,previous,seconds):
    if current is None or previous is None or seconds<=0 or current<previous:return None
    return round((current-previous)/seconds,2)

class SystemCollector:
    def __init__(self,proc=Path('/proc'),sysroot=Path('/sys'),root='/'):
        self.proc=Path(proc);self.sys=Path(sysroot);self.root=root;self.previous=None
    def read(self,path):
        try:return path.read_text().strip()
        except (OSError,UnicodeError):return ''
    def network(self):
        counters=[]
        for line in self.read(self.proc/'net/dev').splitlines()[2:]:
            if ':' not in line:continue
            name,rest=line.split(':',1);name=name.strip();parts=rest.split()
            if name=='lo' or name.startswith(('sit','veth','docker','br-','tun','tap','wg','tailscale')):continue
            state=self.read(self.sys/'class/net'/name/'operstate')
            if state not in ('up','unknown',''):continue
            try:counters.append((name,int(parts[0]),int(parts[8]),(self.sys/'class/net'/name/'device').exists()))
            except (ValueError,IndexError):continue
        physical=[v for v in counters if v[3]]
        selected=physical or counters
        if not selected:return None,None,''
        return sum(v[1] for v in selected),sum(v[2] for v in selected),','.join(sorted(v[0] for v in selected))
    def collect(self):
        now=time.monotonic();row={k:None for k in COLUMNS};row['timestamp']=int(time.time())
        row['cpu_count']=os.cpu_count() or 1
        row['boot_id']=self.read(self.proc/'sys/kernel/random/boot_id') or None
        values={}
        for line in self.read(self.proc/'meminfo').splitlines():
            try:key,rest=line.split(':',1);values[key]=int(rest.split()[0])*1024
            except (ValueError,IndexError):continue
        row['mem_total_bytes']=values.get('MemTotal')
        row['mem_available_bytes']=values.get('MemAvailable')
        if row['mem_available_bytes'] is None and 'MemFree' in values:
            row['mem_available_bytes']=sum(values.get(k,0) for k in ('MemFree','Buffers','Cached'))
        if row['mem_total_bytes'] is not None and row['mem_available_bytes'] is not None:
            row['mem_used_bytes']=max(0,row['mem_total_bytes']-row['mem_available_bytes'])
        row['swap_total_bytes']=values.get('SwapTotal')
        if 'SwapTotal' in values and 'SwapFree' in values:row['swap_used_bytes']=max(0,values['SwapTotal']-values['SwapFree'])
        try:row['load_1'],row['load_5']=map(float,self.read(self.proc/'loadavg').split()[:2])
        except ValueError:pass
        try:row['uptime_seconds']=float(self.read(self.proc/'uptime').split()[0])
        except (ValueError,IndexError):pass
        try:
            v=os.statvfs(self.root)
            row.update(disk_total_bytes=v.f_blocks*v.f_frsize,disk_used_bytes=(v.f_blocks-v.f_bfree)*v.f_frsize,disk_available_bytes=v.f_bavail*v.f_frsize)
            dev=os.stat(self.root).st_dev
            d=self.read(self.sys/'dev/block'/f'{os.major(dev)}:{os.minor(dev)}'/'stat').split()
            if len(d)>=7:row['disk_read_bytes']=int(d[2])*512;row['disk_write_bytes']=int(d[6])*512
        except (OSError,ValueError):pass
        row['net_rx_bytes'],row['net_tx_bytes'],row['network_key']=self.network()
        cpu=None
        try:
            first=self.read(self.proc/'stat').splitlines()[0].split()
            if first[0]=='cpu' and len(first)>=6:
                fields=[int(v) for v in first[1:9]];cpu=(sum(fields),fields[3]+fields[4])
        except (ValueError,IndexError):pass
        previous=self.previous
        if previous and previous['row']['boot_id']==row['boot_id']:
            seconds=now-previous['time'];old=previous['row']
            if cpu and previous['cpu']:
                total=cpu[0]-previous['cpu'][0];idle=cpu[1]-previous['cpu'][1]
                if total>0 and 0<=idle<=total:row['cpu_percent']=round(100*(total-idle)/total,2)
            if row['network_key']==old['network_key']:
                row['net_rx_Bps']=rate(row['net_rx_bytes'],old['net_rx_bytes'],seconds)
                row['net_tx_Bps']=rate(row['net_tx_bytes'],old['net_tx_bytes'],seconds)
            row['disk_read_Bps']=rate(row['disk_read_bytes'],old['disk_read_bytes'],seconds)
            row['disk_write_Bps']=rate(row['disk_write_bytes'],old['disk_write_bytes'],seconds)
        self.previous={'row':row,'time':now,'cpu':cpu}
        return row

def public_current(row):
    return {k:v for k,v in row.items() if k not in ('boot_id','network_key','net_rx_bytes','net_tx_bytes','disk_read_bytes','disk_write_bytes')} | {'network_interfaces':row.get('network_key','')}

def aggregate(rows,fields,seconds):
    """Display means, with explicit breaks across reboot/interface/gap boundaries."""
    output=[];bucket=[];key=None;previous=None
    def finish():
        if not bucket:return
        point={'timestamp':bucket[-1]['timestamp'],'break_before':bucket[0].get('_break',False)}
        for field in fields:
            values=[r[field] for r in bucket if r.get(field) is not None]
            point[field]=round(sum(values)/len(values),2) if values else None
        if 'cpu_percent' in fields:
            values=[r['cpu_percent'] for r in bucket if r.get('cpu_percent') is not None]
            point['cpu_peak']=max(values) if values else None
        output.append(point)
    for raw in rows:
        row=dict(raw);newkey=(row['timestamp']//seconds,row.get('boot_id'),row.get('network_key'))
        broken=bool(previous and (row['timestamp']-previous['timestamp']>150 or row.get('boot_id')!=previous.get('boot_id') or row.get('network_key')!=previous.get('network_key')))
        if key!=newkey or broken:finish();bucket=[]
        row['_break']=broken;bucket.append(row);key=newkey;previous=row
    finish();return output

def summarize(rows):
    result={'samples':len(rows),'coverage_seconds':rows[-1]['timestamp']-rows[0]['timestamp'] if rows else 0,
            'cpu_average_percent':None,'cpu_peak_percent':None,'memory_peak_bytes':None,
            'network_rx_bytes':None,'network_tx_bytes':None,'disk_read_bytes':None,'disk_write_bytes':None,
            'network_coverage_seconds':0,'disk_coverage_seconds':0}
    cpu=[r['cpu_percent'] for r in rows if r.get('cpu_percent') is not None]
    mem=[r['mem_used_bytes'] for r in rows if r.get('mem_used_bytes') is not None]
    if cpu:result.update(cpu_average_percent=round(sum(cpu)/len(cpu),2),cpu_peak_percent=max(cpu))
    if mem:result['memory_peak_bytes']=max(mem)
    for a,b in zip(rows,rows[1:]):
        seconds=b['timestamp']-a['timestamp']
        if not a.get('boot_id') or a['boot_id']!=b.get('boot_id') or not 0<seconds<=150:continue
        for kind,fields in [('network',('net_rx_bytes','net_tx_bytes')),('disk',('disk_read_bytes','disk_write_bytes'))]:
            if kind=='network' and a.get('network_key')!=b.get('network_key'):continue
            if any(a.get(k) is None or b.get(k) is None or b[k]<a[k] for k in fields):continue
            names=('network_rx_bytes','network_tx_bytes') if kind=='network' else fields
            for key,name in zip(fields,names):result[name]=(result[name] or 0)+b[key]-a[key]
            result[kind+'_coverage_seconds']+=seconds
    return result
