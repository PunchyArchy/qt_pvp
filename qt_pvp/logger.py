""" Настройка логгера """

from logging.handlers import TimedRotatingFileHandler
from logging import Formatter
from qt_pvp import settings
import logging
import os

logging.getLogger("urllib3").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
if settings.config.getboolean("General", "debug"):
    logger.setLevel(logging.DEBUG)


handler = TimedRotatingFileHandler(
    filename=os.path.join(settings.LOGS_DIR, 'journal.log'),
    when='midnight',
    backupCount=60,
    encoding='utf-8',
    delay=False)

stream_handler = logging.StreamHandler()
formatter = Formatter(
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logger.addHandler(handler)
logger.addHandler(stream_handler)
