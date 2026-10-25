"""Native source validation against a private fake BlueZ bus; never hardware.

Run inside the disposable Arch userspace prepared by desktop/test-input.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from dbus_next import DBusError, Message, MessageType, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

ADDRESS = 'AA:BB:CC:DD:EE:FF'
DEVICE = '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF'
ADAPTER = '/org/bluez/hci0'


def variants(values):
    return {key: Variant('b' if isinstance(value, bool) else 'o' if key == 'Adapter' else 's', value)
            for key, value in values.items()}


class Properties(ServiceInterface):
    def __init__(self, server, adapter=False):
        super().__init__('org.freedesktop.DBus.Properties')
        self.server, self.adapter = server, adapter

    @method()
    def GetAll(self, interface: 's') -> 'a{sv}':
        return variants(self.server.adapter if self.adapter else self.server.device)

    @method()
    def Set(self, interface: 's', key: 's', value: 'v'):
        target = self.server.adapter if self.adapter else self.server.device
        target[key] = value.value
        if key == 'Trusted' and value.value:
            assert self.server.device['Bonded'], 'Trust must follow a saved bond'


class Manager(ServiceInterface):
    def __init__(self, server):
        super().__init__('org.bluez.AgentManager1')
        self.server = server

    @method()
    def RegisterAgent(self, path: 'o', capability: 's'):
        assert capability == 'KeyboardDisplay'
        self.server.agent_path = path
        self.server.registered = True

    @method()
    def UnregisterAgent(self, path: 'o'):
        self.server.registered = False


class Objects(ServiceInterface):
    def __init__(self, server):
        super().__init__('org.freedesktop.DBus.ObjectManager')
        self.server = server

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        return {DEVICE: {'org.bluez.Device1': variants(self.server.device)}} if self.server.available else {}


class Adapter(ServiceInterface):
    def __init__(self, server):
        super().__init__('org.bluez.Adapter1')
        self.server = server

    @method()
    def RemoveDevice(self, path: 'o'):
        assert path == DEVICE
        self.server.removed += 1
        self.server.available = False
        self.server.device.update(Paired=False, Bonded=False, Trusted=False, Connected=False)

    @method()
    def StartDiscovery(self):
        self.server.discovery = True
        self.server.available = True

    @method()
    def StopDiscovery(self):
        self.server.discovery = False


class Device(ServiceInterface):
    def __init__(self, server):
        super().__init__('org.bluez.Device1')
        self.server = server

    @method()
    async def Pair(self):
        s = self.server
        s.pairs += 1
        # A different bus peer and a different device must never solicit consent.
        attacker = await MessageBus(bus_address=s.address).connect()
        reply = await attacker.call(Message(destination=s.agent_owner, path=s.agent_path,
                                  interface='org.bluez.Agent1', member='RequestConfirmation',
                                  signature='ou', body=[DEVICE, 999999]))
        assert reply.message_type == MessageType.ERROR
        attacker.disconnect()
        reply = await s.agent_call('RequestConfirmation', 'ou', [DEVICE + '_OTHER', 999999])
        assert reply.message_type == MessageType.ERROR
        kind = s.scenario
        s.gui_waiting = True
        if kind in ('confirm', 'cancel', 'eof', 'reject', 'repair', 'unbonded', 'gui'):
            reply = await s.agent_call('RequestConfirmation', 'ou', [DEVICE, 123456])
        elif kind == 'passkey':
            reply = await s.agent_call('RequestPasskey', 'o', [DEVICE])
            assert reply.body == [42]
        elif kind == 'pin':
            reply = await s.agent_call('RequestPinCode', 'o', [DEVICE])
            assert reply.body == ['0000']
        elif kind == 'display':
            reply = await s.agent_call('DisplayPasskey', 'ouq', [DEVICE, 123456, 0])
        else:
            raise AssertionError(kind)
        if reply.message_type == MessageType.ERROR:
            raise DBusError('org.bluez.Error.AuthenticationRejected', 'Rejected')
        s.device.update(Paired=True, Bonded=kind != 'unbonded')

    @method()
    def CancelPairing(self):
        self.server.cancelled += 1

    @method()
    def Connect(self):
        assert self.server.device['Bonded']
        self.server.connects += 1
        self.server.device.update(Connected=True, ServicesResolved=True)


class Server:
    def __init__(self, bus, address):
        self.bus, self.address = bus, address
        bus.add_message_handler(self.observe)
        bus.export('/', Objects(self))
        bus.export('/org/bluez', Manager(self))
        bus.export(ADAPTER, Adapter(self))
        bus.export(ADAPTER, Properties(self, adapter=True))
        bus.export(DEVICE, Device(self))
        bus.export(DEVICE, Properties(self))

    def reset(self, scenario):
        self.scenario = scenario
        self.available = True
        self.registered = self.discovery = False
        self.pairs = self.connects = self.removed = self.cancelled = 0
        self.gui_waiting = False
        self.adapter = {'Powered': True, 'Pairable': False}
        self.device = {'Address': ADDRESS, 'Adapter': ADAPTER, 'Alias': 'Fixture Magic Keyboard',
                       'Paired': scenario in ('repair', 'repair_reject', 'bonded'), 'Bonded': scenario == 'bonded', 'Trusted': False,
                       'Connected': False, 'ServicesResolved': False}

    def observe(self, message):
        if message.message_type != MessageType.METHOD_CALL:
            return
        if message.member == 'RegisterAgent':
            self.agent_owner = message.sender
        # dbus-next supplies built-in ObjectManager/Properties handlers before
        # exported methods; explicitly supply the fixture's dynamic properties.
        if message.interface == 'org.freedesktop.DBus.ObjectManager' and message.member == 'GetManagedObjects':
            objects = {DEVICE: {'org.bluez.Device1': variants(self.device)}} if self.available else {}
            return Message.new_method_return(message, 'a{oa{sa{sv}}}', [objects])
        if message.interface == 'org.freedesktop.DBus.Properties':
            values = self.adapter if message.path == ADAPTER else self.device
            if message.member == 'GetAll':
                return Message.new_method_return(message, 'a{sv}', [variants(values)])
            if message.member == 'Set':
                key, value = message.body[1], message.body[2].value
                if key == 'Trusted' and value:
                    assert self.device['Bonded'], 'Trust must follow a saved bond'
                values[key] = value
                return Message.new_method_return(message)

    async def agent_call(self, member, signature, body):
        return await self.bus.call(Message(destination=self.agent_owner, path=self.agent_path,
                                  interface='org.bluez.Agent1', member=member,
                                  signature=signature, body=body))


async def wire_case(server, scenario, root):
    server.reset(scenario)
    runtime = root / scenario
    runtime.mkdir(mode=0o700)
    env = {**os.environ, 'DBUS_SYSTEM_BUS_ADDRESS': server.address, 'XDG_RUNTIME_DIR': str(runtime)}
    process = await asyncio.create_subprocess_exec('/usr/bin/python3', '/usr/libexec/omarchy-bluetooth-pair', ADDRESS,
                  env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    events = []
    async for line in process.stdout:
        record = json.loads(line)
        events.append(record)
        if record['event'] == 'prompt':
            assert server.connects == 0 and not server.device['Trusted']
            assert record.get('code') != '999999', 'Unsolicited request reached UI'
            if scenario == 'eof':
                process.stdin.close()
                continue
            if scenario == 'cancel':
                response = {'action': 'cancel'}
            else:
                response = {'action': 'reply', 'id': record['id'], 'accept': scenario not in ('reject', 'repair_reject'),
                            'value': '000042' if record['kind'] == 'passkey' else '0000'}
            process.stdin.write((json.dumps(response) + '\n').encode())
            await process.stdin.drain()
    await asyncio.wait_for(process.wait(), 15)
    errors = (await process.stderr.read()).decode()
    success = scenario not in ('cancel', 'eof', 'reject', 'repair_reject', 'unbonded')
    assert (process.returncode == 0) == success, (scenario, process.returncode, events, errors)
    assert not server.registered and not server.adapter['Pairable'] and not server.discovery
    assert server.connects == int(success)
    assert server.removed == int(scenario == 'repair')
    assert server.pairs == int(scenario not in ('repair_reject', 'bonded'))
    print(json.dumps({'case': scenario, 'passed': True, 'exit': process.returncode}), flush=True)


async def gui_case(server, accept, scenario='gui', wrapper=False):
    server.reset(scenario)
    result = Path(os.environ['XDG_RUNTIME_DIR']) / 'pairing-gui-result'
    result.write_text('')
    result.chmod(0o600)
    env = {**os.environ, 'DBUS_SYSTEM_BUS_ADDRESS': server.address,
           'OMARCHY_PAIR_ADDRESS': ADDRESS, 'OMARCHY_PAIR_RESULT': str(result),
           'QT_QUICK_BACKEND': 'software', 'QSG_RENDER_LOOP': 'basic'}
    if wrapper:
        # Stub only the power-state query, never pairing/authentication.
        tools = Path('/tmp/bluetooth-query-fixture')
        tools.mkdir(exist_ok=True)
        stub = tools / 'bluetoothctl'
        stub.write_text('#!/bin/sh\n[ "$1" = show ] || exit 99\nprintf "Powered: yes\\n"\n')
        stub.chmod(0o755)
        env.update(PATH=str(tools) + ':' + os.environ['PATH'], OMARCHY_PATH='/tmp/pairing-desktop')
        command = ['bash', '/tmp/pairing-cli.sh', 'pair', ADDRESS]
    else:
        command = ['qs', '-p', '/tmp/pairing-ui/shell.qml']
    process = await asyncio.create_subprocess_exec(*command, env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        for _ in range(400):
            if server.gui_waiting:
                break
            if process.returncode is not None:
                raise AssertionError((await process.stdout.read()).decode())
            await asyncio.sleep(.025)
        assert server.gui_waiting, 'Pairing UI did not reach a confirmation request'
        # Render-only settling in the isolated fixture, not production timing.
        await asyncio.sleep(.4)
        if accept:
            screenshot = '/tmp/pairing-confirm.png' if scenario == 'gui' else '/tmp/pairing-' + scenario + '.png'
            capture = await asyncio.create_subprocess_exec('grim', '-c', screenshot)
            assert await capture.wait() == 0
        assert not server.device['Bonded'] and server.connects == 0
        keys = (['000042' if scenario == 'passkey' else '0000', '-k', 'Return']
                if scenario in ('passkey', 'pin') else ['-k', 'Tab', '-k', 'Return']) if accept else ['-k', 'Escape']
        action = await asyncio.create_subprocess_exec('/usr/libexec/omarchy-wtype', *keys)
        assert await action.wait() == 0
        await asyncio.wait_for(process.wait(), 10)
        output = (await process.stdout.read()).decode()
        assert 'ERROR' not in output, output
        if wrapper:
            assert process.returncode == (0 if accept else 2), (process.returncode, output)
        else:
            assert result.read_text().strip() == ('0' if accept else '2'), (result.read_text(), output)
        assert server.connects == int(accept)
        assert not server.registered and not server.adapter['Pairable']
        print(json.dumps({'case': ('wrapper-' if wrapper else 'gui-') + scenario + ('-approve' if accept else '-cancel'), 'passed': True}), flush=True)
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
            Path('/tmp/pairing-ui.log').write_bytes(await process.stdout.read())
        result.unlink(missing_ok=True)


async def main():
    daemon = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'], stdout=subprocess.PIPE)
    address = daemon.stdout.readline().decode().strip()
    bus = await MessageBus(bus_address=address).connect()
    await bus.request_name('org.bluez')
    server = Server(bus, address)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if '--gui' in sys.argv:
                for accept, scenario in ((True, 'gui'), (False, 'gui'), (True, 'passkey'), (True, 'pin')):
                    await asyncio.wait_for(gui_case(server, accept, scenario), 25)
                for accept in (True, False):
                    await asyncio.wait_for(gui_case(server, accept, wrapper=True), 25)
            else:
                for scenario in ('confirm', 'passkey', 'pin', 'display', 'cancel', 'eof', 'reject', 'unbonded', 'repair', 'repair_reject', 'bonded'):
                    await asyncio.wait_for(wire_case(server, scenario, root), 25)
    finally:
        bus.disconnect()
        daemon.terminate()
        daemon.wait(timeout=5)


if __name__ == '__main__':
    asyncio.run(main())
