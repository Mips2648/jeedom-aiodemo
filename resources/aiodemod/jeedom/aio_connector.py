import logging
import json
import asyncio
from typing import Callable, Awaitable
import aiohttp
from collections.abc import Mapping

class Listener():
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, 'instance'):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self, socket_host: str, socket_port: int, on_message: Callable[[list], Awaitable[None]]) -> None:
        self._socket_host = socket_host
        self._socket_port = socket_port
        self._on_message = on_message
        self._logger = logging.getLogger(__name__)

    @staticmethod
    def create_listen_task(socket_host: str, socket_port: int, on_message: Callable[[list], Awaitable[None]]):
        listener = Listener(socket_host, socket_port, on_message)
        return asyncio.create_task(listener._listen())

    async def _listen(self):
        try:
            server = await asyncio.start_server(self._handle_read, self._socket_host, port=self._socket_port)

            async with server:
                self._logger.info('Listening on %s:%s', self._socket_host, self._socket_port)
                await server.serve_forever()
        except asyncio.CancelledError:
            self._logger.info("Listening cancelled")

    async def _handle_read(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        data = await reader.read()
        message = data.decode()
        addr = writer.get_extra_info('peername')
        self._logger.debug("Received %s from %s", message, addr)

        writer.close()
        self._logger.debug("Close connection")
        await writer.wait_closed()
        await self._on_message(json.loads(message))

class Publisher():
    def __init__(self, callback_url: str, api_key: str, cycle: float = 0.5) -> None:
        self._jeedom_session = aiohttp.ClientSession()
        self._callback_url = callback_url
        self._api_key = api_key
        self._cycle = cycle if (cycle > 0 and cycle < 10) else 0.5
        self._logger = logging.getLogger(__name__)

        self.__changes = {}

    def create_send_task(self):
        return asyncio.create_task(self._send_async())

    async def test_callback(self):
        try:
            async with self._jeedom_session.get(self._callback_url + '?test=1&apikey=' + self._api_key) as resp:
                if resp.status != 200:
                    self._logger.error("Please check your network configuration page: %s-%s", resp.status, resp.reason)
                    return False
        except Exception as e:
            self._logger.error('Callback error: %s. Please check your network configuration page', e)
            return False
        return True

    async def _send_async(self):
        self._logger.debug("send_async started")
        try:
            while True:
                if len(self.__changes)>0:
                    changes = self.__changes
                    self.__changes = {}
                    await self.send_to_jeedom(changes)
                await asyncio.sleep(self._cycle)
        except asyncio.CancelledError:
            self._logger.debug("send_async cancelled")


    async def send_to_jeedom(self, payload):
        self._logger.debug('Send to jeedom :  %s', payload)
        async with self._jeedom_session.post(self._callback_url + '?apikey=' + self._api_key, json=payload) as resp:
            if resp.status != 200:
                self._logger.error('Error on send request to jeedom, return %s-%s', resp.status, resp.reason)
                return False
        return True

    async def add_change(self, key: str, value):
        if key.find('::') != -1:
            tmp_changes = {}
            changes = value
            for k in reversed(key.split('::')):
                if k not in tmp_changes:
                    tmp_changes[k] = {}
                tmp_changes[k] = changes
                changes = tmp_changes
                tmp_changes = {}

            await self.__merge_dict(self.__changes,changes)
        else:
            self.__changes[key] = value

    async def __merge_dict(self, d1: dict, d2: dict):
        for k,v2 in d2.items():
            v1 = d1.get(k) # returns None if v1 has no value for this key
            if isinstance(v1, Mapping) and isinstance(v2, Mapping):
                await self.__merge_dict(v1, v2)
            else:
                d1[k] = v2
