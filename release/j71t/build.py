#!/usr/bin/env python3
"""Produce one coherent public J71t release: root, recovery, Pongo and manifest."""
from release.j71b.build import main

if __name__ == '__main__':
    main('j71t')
