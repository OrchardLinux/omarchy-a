#!/usr/bin/env python3
"""A release's install.sh: installs the orchard command and runs `orchard install` for that release.

  python -m release.install_script --index URL --url URL --output install.sh
"""
import argparse
from pathlib import Path
import re

TEMPLATE = Path(__file__).with_name('install.sh')


def write(output, index, url):
    """install.sh at OUTPUT for the release whose index is INDEX; URL is where the script itself is fetched from."""
    for value in (index, url):
        if not re.fullmatch(r"[A-Za-z0-9:/._~+-]+", value):
            raise ValueError(f'Not a plain URL or path: {value}')
    text = TEMPLATE.read_text().replace('@INDEX@', "'" + index + "'").replace('@URL@', url)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    output.chmod(0o755)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--index', required=True, help="the release's index.toml: its URL, or a path for a local build")
    parser.add_argument('--url', required=True, help='where this install.sh is published')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(write(args.output, args.index, args.url))


if __name__ == '__main__':
    main()
