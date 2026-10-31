"""Pairing request policy, independent of D-Bus and the presentation layer."""
import asyncio
import re
import secrets


class Rejected(Exception):
    pass


def response_value(kind, value):
    if kind in ('confirm', 'authorize', 'repair'):
        return None
    if not isinstance(value, str):
        raise ValueError('Enter a valid pairing code')
    if kind == 'passkey':
        if not re.fullmatch(r'[0-9]{1,6}', value):
            raise ValueError('Enter up to six digits')
        return int(value)
    if kind == 'pin':
        if not re.fullmatch(r'[\x20-\x7e]{1,16}', value):
            raise ValueError('Enter a PIN of 1–16 printable characters')
        return value
    raise ValueError('Unexpected pairing response')


def needs_repair(properties):
    return not properties.get('Bonded', False) and bool(properties.get('Paired') or properties.get('Trusted'))


class PromptBroker:
    def __init__(self, emit):
        self.emit = emit
        self.pending = None

    async def request(self, kind, **fields):
        if self.pending is not None:
            raise Rejected('Another authentication request is active')
        request_id = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self.pending = (request_id, kind, future)
        self.emit({'event': 'prompt', 'id': request_id, 'kind': kind, **fields})
        try:
            return await asyncio.wait_for(future, 90)
        except asyncio.TimeoutError:
            raise Rejected('Pairing confirmation timed out') from None
        finally:
            self.pending = None
            self.emit({'event': 'clear'})

    def reply(self, message):
        if self.pending is None or message.get('id') != self.pending[0]:
            return False
        request_id, kind, future = self.pending
        if future.done():
            return False
        if message.get('accept') is not True:
            future.set_exception(Rejected('Pairing rejected'))
            return True
        try:
            value = response_value(kind, message.get('value'))
        except ValueError as error:
            self.emit({'event': 'validation_error', 'message': str(error)})
            return False
        future.set_result(value)
        return True

    def cancel(self):
        if self.pending and not self.pending[2].done():
            self.pending[2].set_exception(Rejected('Pairing cancelled'))
