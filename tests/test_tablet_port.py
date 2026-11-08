import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]

def load(name, path):
    loader=importlib.machinery.SourceFileLoader(name,str(PROJECT/path))
    spec=importlib.util.spec_from_loader(name,loader)
    mod=importlib.util.module_from_spec(spec); loader.exec_module(mod); return mod

p=load('power','system/overlay/usr/libexec/omarchy-powerd')

class TabletPort(unittest.TestCase):





    def test_home_power_overlap_in_either_order_cancels_power(self):
        event=lambda code,v: p.INPUT_EVENT.pack(1,0,1,code,v)
        for codes in ([(116,1),(172,1),(172,0),(116,0)],[(172,1),(116,1),(172,0),(116,0)]):
            f=p.KeyFilter(); result=[]
            for code,v in codes: result+=f.events(event(code,v))
            self.assertNotIn('power',[name for name,when in result])
        f=p.KeyFilter()
        self.assertEqual(f.events(event(116,1)),[])
        self.assertEqual(f.events(event(116,0)),[('power',1.0)])


    def test_no_false_client_remap_and_native_touch(self):
        source=(PROJECT/'desktop/shell/shell/Ui/ScreenMoveRemap.qml').read_text()
        self.assertIn('readonly property bool remapping: false',source)
        self.assertNotIn('Timer {',source)
        tree=ET.fromstring((PROJECT/'desktop/shell/labwc-rc.xml').read_text())
        touch=next(t for t in tree.findall('touch') if t.get('deviceName')=='iPad6,11 Touchscreen')
        self.assertEqual(touch.get('mapToOutput'),'eDP-1')
        self.assertEqual(touch.get('mouseEmulation'),'no')



if __name__=='__main__': unittest.main()
