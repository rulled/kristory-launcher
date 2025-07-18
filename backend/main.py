
import sys
import os
import logging

# Это гарантирует, что мы можем использовать абсолютные импорты (from backend. ...),
# независимо от того, как запускается скрипт.
# При сборке через PyInstaller, spec файл должен содержать `pathex=['.']`,
# чтобы корень проекта был в sys.path
from backend.api_server import run


if __name__ == "__main__":
    # Логирование теперь полностью настраивается внутри api_server.run()
    # Просто запускаем сервер в режиме отладки.
    logging.info("Backend process initiated.")
    run(debug_mode=True)
