"""The Wi-Fi list holds still while a passphrase is typed (#110)."""
from pathlib import Path
import re
import unittest

PANEL = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/plugins/panels/network/Panel.qml'


def block(text, start):
    """The braced body that follows START."""
    at = text.index(start)
    depth, i = 0, text.index('{', at)
    for j in range(i, len(text)):
        depth += {'{': 1, '}': -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    raise AssertionError(start)


class WifiPasswordHold(unittest.TestCase):
    def test_the_list_is_not_replaced_while_the_prompt_is_open(self):
        text = PANEL.read_text()
        body = block(text, 'function rebuildWifiRows()')
        hold = body.index('if (passwordSsid !== "") return')
        # Connect results are still seen, and the hold comes before the list is replaced.
        self.assertLess(body.index('checkActionCompletion(network)'), hold)
        self.assertLess(hold, body.index('wifiNetworks = nets'))

    def test_the_list_catches_up_when_the_prompt_closes(self):
        body = block(PANEL.read_text(), 'onPasswordSsidChanged:')
        self.assertRegex(body, re.compile(r'if \(passwordSsid === ""\) rebuildWifiRows\(\)'))


if __name__ == '__main__':
    unittest.main()
