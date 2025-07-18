
import os
import json
import shutil
import logging
from .paths import get_mods_dir, get_disabled_mods_dir, get_managed_mods_path

logger = logging.getLogger(__name__)

class ModManager:
    """Управляет модами на основе конфигурационного файла: сканирует, включает и отключает их."""
    def __init__(self, config):
        """Инициализирует менеджер модов."""
        self.config = config
        self.mods_dir = get_mods_dir(config)
        self.disabled_mods_dir = get_disabled_mods_dir(config)
        self.managed_mods = self._load_managed_mods_config()

    def _load_managed_mods_config(self):
        """Загружает конфигурацию управляемых модов из JSON-файла."""
        config_path = get_managed_mods_path()
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                logger.info(f"Загрузка конфигурации управляемых модов из {config_path}")
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Файл конфигурации модов не найден: {config_path}. Список модов будет пуст.")
            return []
        except json.JSONDecodeError:
            logger.error(f"Ошибка парсинга JSON в файле: {config_path}. Список модов будет пуст.")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при загрузке конфигурации модов: {e}")
            return []

    def get_all_mods(self):
        """
        Возвращает информацию только о тех модах, которые указаны в managed_mods.json.
        
        Returns:
            list: Список словарей, где каждый словарь представляет мод с его статусом.
        """
        if not self.managed_mods:
            return []

        # If game path is not set, we can't have mods.
        if not self.mods_dir:
            logger.warning("Game directory is not set. Cannot list mods.")
            return []

        # Получаем списки файлов из папок
        enabled_files = set()
        if os.path.exists(self.mods_dir):
            try:
                enabled_files = set(os.listdir(self.mods_dir))
            except OSError as e:
                logger.error(f"Не удалось прочитать папку mods: {e}")


        disabled_files = set()
        if os.path.exists(self.disabled_mods_dir):
            try:
                disabled_files = set(os.listdir(self.disabled_mods_dir))
            except OSError as e:
                logger.error(f"Не удалось прочитать папку mods_disabled: {e}")

        result_mods = []
        for mod_info in self.managed_mods:
            filename = mod_info.get('filename')
            if not filename:
                continue

            # Определяем статус мода
            if filename in enabled_files:
                status = 'enabled'
            elif filename in disabled_files:
                status = 'disabled'
            else:
                # Если мода нет ни в одной из папок, пропускаем его
                logger.warning(f"Управляемый мод '{filename}' не найден ни в папке mods, ни в mods_disabled.")
                continue

            result_mods.append({
                'filename': filename,
                'name': mod_info.get('name', filename), # Если нет красивого имени, используем имя файла
                'description': mod_info.get('description', ''),
                'status': status
            })
        
        logger.info(f"Найдено {len(result_mods)} управляемых модов для отображения.")
        return result_mods

    def set_mod_state(self, mod_filename, enable):
        """Включает или отключает мод, перемещая его файл. Теперь логирует каждую ситуацию явно."""
        logger.info(f"[ModManager] set_mod_state вызван: filename='{mod_filename}', enable={enable}")
        if not self.mods_dir or not self.disabled_mods_dir:
            logger.error("Game directory not set, cannot change mod state.")
            return False

        # Проверяем, является ли этот мод управляемым
        if not any(mod['filename'] == mod_filename for mod in self.managed_mods):
            logger.warning(f"Попытка изменить состояние неуправляемого мода: '{mod_filename}'. Операция отклонена, т.к. его нет в managed_mods.json.")
            return False

        enabled_path = os.path.join(self.mods_dir, mod_filename)
        disabled_path = os.path.join(self.disabled_mods_dir, mod_filename)

        enabled_exists = os.path.exists(enabled_path)
        disabled_exists = os.path.exists(disabled_path)

        if enable:
            if enabled_exists:
                logger.info(f"Попытка включить мод '{mod_filename}', который уже включён (файл уже в mods). Операция пропущена.")
                return True
            elif disabled_exists:
                try:
                    os.makedirs(self.mods_dir, exist_ok=True)
                    shutil.move(disabled_path, enabled_path)
                    logger.info(f"Мод '{mod_filename}' был успешно включён (перемещён из mods_disabled в mods).")
                    return True
                except Exception as e:
                    logger.error(
                        f"Ошибка перемещения файла '{mod_filename}' при включении: {e}\n"
                        f"Исходный путь: {disabled_path}\n"
                        f"Папка назначения: {enabled_path}\n"
                        f"Содержимое mods: {os.listdir(self.mods_dir) if os.path.exists(self.mods_dir) else 'Папка не найдена'}\n"
                        f"Содержимое mods_disabled: {os.listdir(self.disabled_mods_dir) if os.path.exists(self.disabled_mods_dir) else 'Папка не найдена'}"
                    )
                    return False
            else:
                logger.error(
                    f"Не удалось включить мод '{mod_filename}': файл не найден ни в mods, ни в mods_disabled!\n"
                    f"Ожидалось: {disabled_path} -> {enabled_path}\n"
                    f"Содержимое mods: {os.listdir(self.mods_dir) if os.path.exists(self.mods_dir) else 'Папка не найдена'}\n"
                    f"Содержимое mods_disabled: {os.listdir(self.disabled_mods_dir) if os.path.exists(self.disabled_mods_dir) else 'Папка не найдена'}"
                )
                return False
        else:
            if disabled_exists:
                logger.info(f"Попытка выключить мод '{mod_filename}', который уже выключен (файл уже в mods_disabled). Операция пропущена.")
                return True
            elif enabled_exists:
                try:
                    os.makedirs(self.disabled_mods_dir, exist_ok=True)
                    shutil.move(enabled_path, disabled_path)
                    logger.info(f"Мод '{mod_filename}' был успешно выключен (перемещён из mods в mods_disabled).")
                    return True
                except Exception as e:
                    logger.error(
                        f"Ошибка перемещения файла '{mod_filename}' при выключении: {e}\n"
                        f"Исходный путь: {enabled_path}\n"
                        f"Папка назначения: {disabled_path}\n"
                        f"Содержимое mods: {os.listdir(self.mods_dir) if os.path.exists(self.mods_dir) else 'Папка не найдена'}\n"
                        f"Содержимое mods_disabled: {os.listdir(self.disabled_mods_dir) if os.path.exists(self.disabled_mods_dir) else 'Папка не найдена'}"
                    )
                    return False
            else:
                logger.error(
                    f"Не удалось выключить мод '{mod_filename}': файл не найден ни в mods, ни в mods_disabled!\n"
                    f"Ожидалось: {enabled_path} -> {disabled_path}\n"
                    f"Содержимое mods: {os.listdir(self.mods_dir) if os.path.exists(self.mods_dir) else 'Папка не найдена'}\n"
                    f"Содержимое mods_disabled: {os.listdir(self.disabled_mods_dir) if os.path.exists(self.disabled_mods_dir) else 'Папка не найдена'}"
                )
                return False
