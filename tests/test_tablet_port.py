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
    pass





    def test_home_power_overlap_uses_upstream_screenshot_buttons(self):
        p=load('power', 'system/overlay/usr/libexec/omarchy-powerd')
        for edges in ((('power', True), ('home', True), ('power', False), ('home', False)),
                      (('home', True), ('power', True), ('home', False), ('power', False))):
            buttons=p.Buttons()
            result=[buttons.edge(name, down, 10+i/10, True) for i,(name,down) in enumerate(edges)]
            self.assertEqual([x for x in result if x], ['home', 'screenshot'])
            self.assertTrue(buttons.home_in_combo)


if __name__=='__main__': unittest.main()
