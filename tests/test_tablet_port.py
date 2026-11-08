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










if __name__=='__main__': unittest.main()
