
import os
import sys

def get_launcher_root_dir():
    """
    Возвращает корневую директорию лаунчера.
    В режиме разработки это корень проекта, в собранном .exe - папка с исполняемым файлом.
    """
    if getattr(sys, 'frozen', False):
        # В собранном .exe
        return os.path.dirname(sys.executable)
    else:
        # В режиме разработки
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def get_data_dir():
    """
    Возвращает путь к папке .kristory внутри директории лаунчера.
    Это централизованное место для хранения всех данных лаунчера.
    """
    return os.path.join(get_launcher_root_dir(), '.kristory')

def get_game_dir(config):
    """
    Возвращает корневую папку для данных ИГРЫ (моды, версии).
    Этот путь берется исключительно из конфигурации.
    Возвращает None, если путь не задан.
    """
    if config:
        return config.get('game_settings', {}).get('game_directory') or None
    return None

def get_config_path():
    """
    Возвращает абсолютный путь к файлу конфигурации launcher_config.json.
    """
    return os.path.join(get_data_dir(), 'launcher_config.json')

def get_logs_dir():
    """
    Всегда возвращает путь к папке logs в папке данных лаунчера.
    """
    return os.path.join(get_data_dir(), 'logs')

def get_renders_dir():
    """
    Всегда возвращает путь к папке renders в папке данных лаунчера.
    """
    return os.path.join(get_data_dir(), 'renders')

def get_mods_dir(config):
    """
    Возвращает путь к папке с включенными модами внутри папки ИГРЫ.
    """
    game_dir = get_game_dir(config)
    return os.path.join(game_dir, 'mods') if game_dir else None

def get_disabled_mods_dir(config):
    """
    Возвращает путь к папке с выключенными модами внутри папки ИГРЫ.
    """
    game_dir = get_game_dir(config)
    return os.path.join(game_dir, 'mods_disabled') if game_dir else None

def get_authlib_path():
    """
    Возвращает путь к файлу authlib-injector.jar внутри папки данных лаунчера.
    """
    return os.path.join(get_data_dir(), 'authlib-injector.jar')

def get_managed_mods_path():
    """
    Получает путь к файлу managed_mods.json, работая как в режиме разработки,
    так и в собранном .exe (PyInstaller).
    """
    if getattr(sys, 'frozen', False):
        # В собранном .exe файл лежит в папке backend.
        base_path = sys._MEIPASS
        return os.path.join(base_path, 'backend', 'managed_mods.json')
    else:
        # Режим разработки: файл лежит в той же папке, что и этот скрипт (backend).
        return os.path.join(os.path.dirname(__file__), 'managed_mods.json')

def get_initial_config_path():
    """
    Возвращает путь к launcher_config.json (для первого запуска).
    """
    return get_config_path()


def ensure_directories_exist(config):
    """
    Создает все необходимые директории на основе конфига.
    Эта функция должна вызываться при операциях, требующих наличия папок.
    """
    # Папки данных лаунчера
    os.makedirs(get_data_dir(), exist_ok=True)
    os.makedirs(get_logs_dir(), exist_ok=True)
    os.makedirs(get_renders_dir(), exist_ok=True)
    
    # Папки данных игры (только если путь задан)
    game_dir = get_game_dir(config)
    if not game_dir:
        # Не бросаем ошибку, просто выходим, т.к. папки игры еще не должны существовать
        return

    os.makedirs(game_dir, exist_ok=True)
    mods_dir = get_mods_dir(config)
    if mods_dir:
        os.makedirs(mods_dir, exist_ok=True)
    
    disabled_mods_dir = get_disabled_mods_dir(config)
    if disabled_mods_dir:
        os.makedirs(disabled_mods_dir, exist_ok=True)
