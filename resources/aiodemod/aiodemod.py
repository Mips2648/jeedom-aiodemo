import logging
import argparse
import random
import sys
import os
import signal
import asyncio
import functools

from config import Config
from jeedom.utils import Utils
from jeedom.aio_connector import Listener, Publisher

class AIODemod:
    ANIMALS = {
        0: 'Cat',
        1: 'Dog',
        2: 'Duck',
        3: 'Sheep',
        4: 'Horse',
        5: 'Cow',
        6: 'Goat',
        7: 'Rabbit'
    }

    def __init__(self, config_: Config) -> None:
        self._config = config_
        self._listen_task = None
        self._send_task = None
        self._logger = logging.getLogger(__name__)

        self._jeedom_publisher = None

    async def main(self):
        self._jeedom_publisher = Publisher(self._config.callback_url, self._config.api_key, self._config.cycle)

        if not await self._jeedom_publisher.test_callback():
            return

        self._listen_task = Listener.create_listen_task(self._config.socket_host, self._config.socket_port, self._on_socket_message)
        self._send_task = self._jeedom_publisher.create_send_task()

        self._search_task = asyncio.create_task(self._search_animals())

        await self.add_signal_handler()
        await asyncio.sleep(1) # allow all tasks to start

        self._logger.info("Ready")
        await asyncio.gather(self._listen_task, self._send_task)

    async def add_signal_handler(self):
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, functools.partial(self._ask_exit, signal.SIGINT))
        loop.add_signal_handler(signal.SIGTERM, functools.partial(self._ask_exit, signal.SIGTERM))

    async def _on_socket_message(self, message):
        if message['apikey'] != self._config.api_key:
            self._logger.error('Invalid apikey from socket : %s', message)
            return
        try:
            if message['action'] == 'think':
                await self._think(message['message'])
            elif message['action'] == 'ping':
                for i in range(1, 4):
                    await self._jeedom_publisher.send_to_jeedom({'pingpong':f'ping {i}'})
                    await asyncio.sleep(2)
                    await self._jeedom_publisher.send_to_jeedom({'pingpong':f'pong {i}'})
                    await asyncio.sleep(2)
            else:
                self._logger.warning('Unknown action: %s', message['action'])
        except Exception as e:
            self._logger.error('Send command to daemon error: %s', e)

    async def _think(self, message):
        random_int = random.randint(3, 15)
        self._logger.info("==> think on received '%s' during %is", message, random_int)
        await self._jeedom_publisher.send_to_jeedom({'alert':f"Let me think about '{message}' during {random_int}s"})
        await asyncio.sleep(random_int)
        self._logger.info("==> '%s' was an interesting information, thanks for the nap", message)
        await self._jeedom_publisher.send_to_jeedom({'alert':f"'{message}' was an interesting information, thanks for the nap"})

    async def _search_animals(self):
        self._logger.info("Start searching animals")
        try:
            max_int = len(self.ANIMALS) - 1
            while True:
                animal = self.ANIMALS[random.randint(0, max_int)]
                nbr = random.randint(0, 97)
                self._logger.info("I found %i %s(s)", nbr, animal.lower())
                await self._jeedom_publisher.add_change(animal, nbr)
                await asyncio.sleep(random.randint(0, 2))
        except asyncio.CancelledError:
            self._logger.info("Stop searching animals")

    def _ask_exit(self, sig):
        self._logger.info("Signal %i caught, exiting...", sig)
        self.close()

    def close(self):
        self._logger.debug('Cancel all tasks')
        self._search_task.cancel()
        self._listen_task.cancel()
        self._send_task.cancel()


# ----------------------------------------------------------------------------

def get_args():
    parser = argparse.ArgumentParser(description='mqttdiscoveryd Daemon for Jeedom plugin')
    parser.add_argument("--loglevel", help="Log Level for the daemon", type=str)
    parser.add_argument("--socketport", help="Socket Port", type=int)
    parser.add_argument("--cycle", help="cycle", type=float)
    parser.add_argument("--callback", help="Jeedom callback url", type=str)
    parser.add_argument("--apikey", help="Plugin API Key", type=str)
    parser.add_argument("--pid", help="daemon pid", type=str)

    return parser.parse_args()

def shutdown():
    _LOGGER.info("Shuting down")
    try:
        _LOGGER.debug("Removing PID file %s", config.pid_filename)
        os.remove(config.pid_filename)
    except:
        pass

    _LOGGER.debug("Exit 0")
    sys.stdout.flush()
    os._exit(0)

# ----------------------------------------------------------------------------

args = get_args()
config = Config(**vars(args))

Utils.init_logger(config.log_level)
_LOGGER = logging.getLogger(__name__)
logging.getLogger('asyncio').setLevel(logging.WARNING)

try:
    _LOGGER.info('Starting daemon')
    _LOGGER.info('Log level: %s', config.log_level)
    Utils.write_pid(str(config.pid_filename))

    daemon = AIODemod(config)
    asyncio.run(daemon.main())
except Exception as e:
    exception_type, exception_object, exception_traceback = sys.exc_info()
    filename = exception_traceback.tb_frame.f_code.co_filename
    line_number = exception_traceback.tb_lineno
    _LOGGER.error('Fatal error: %s(%s) in %s on line %s', e, exception_type, filename, line_number)
shutdown()
