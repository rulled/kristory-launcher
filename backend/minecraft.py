
import minecraft_launcher_lib as mll
import logging
import os
import subprocess
import re
import sys
import requests
import shutil
import importlib
import glob

from .paths import get_authlib_path, get_game_dir

logger = logging.getLogger(__name__)

AUTHLIB_API_URL = "https://api.github.com/repos/yushijinhun/authlib-injector/releases/latest"

def get_latest_authlib_url():
    """
    Получает URL последней версии authlib-injector.jar через GitHub API,
    чтобы избежать проблем с версионированными именами файлов.
    """
    logger.info(f"Запрос последней версии authlib-injector с GitHub API: {AUTHLIB_API_URL}")
    try:
        response = requests.get(AUTHLIB_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        assets = data.get('assets', [])

        for asset in assets:
            asset_name = asset.get('name', '')
            # Ищем основной JAR, исключая javadoc и sources
            if asset_name.startswith('authlib-injector-') and asset_name.endswith('.jar') and 'javadoc' not in asset_name and 'sources' not in asset_name:
                download_url = asset.get('browser_download_url')
                logger.info(f"Найдена ссылка для скачивания authlib-injector: {download_url}")
                return download_url
        
        logger.error("В последнем релизе authlib-injector не найден подходящий .jar файл.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к GitHub API для authlib-injector: {e}")
        return None

def download_authlib_injector(authlib_path):
    """Скачивает authlib-injector.jar, если он отсутствует, используя динамическую ссылку."""
    if not os.path.exists(authlib_path):
        logger.info("authlib-injector.jar не найден, скачиваю последнюю версию...")
        try:
            download_url = get_latest_authlib_url()
            if not download_url:
                raise ValueError("Не удалось получить URL для скачивания authlib-injector.")

            logger.info(f"Использую URL: {download_url}")
            os.makedirs(os.path.dirname(authlib_path), exist_ok=True)
            response = requests.get(download_url, stream=True, timeout=30, allow_redirects=True)
            logger.info(f"Статус ответа: {response.status_code}")
            response.raise_for_status()
            
            with open(authlib_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"authlib-injector.jar успешно скачан в {authlib_path}.")

        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"Не удалось скачать authlib-injector: {e}")
            raise RuntimeError(f"Не удалось скачать authlib-injector: {e}") from e

def find_java_windows() -> str | None:
    """Ищет javaw.exe в стандартных местах Windows."""
    search_patterns = [
        r"%ProgramFiles%\Java\jdk-*\bin\javaw.exe",
        r"%ProgramFiles%\Eclipse Adoptium\jdk-*\bin\javaw.exe",
        r"%ProgramFiles%\Microsoft\jdk-*\bin\javaw.exe",
        r"%ProgramFiles(x86)%\Java\jdk-*\bin\javaw.exe",
    ]
    for pattern in search_patterns:
        path = os.path.expandvars(pattern)
        matches = glob.glob(path)
        if matches:
            return matches[0]
    return None

class MinecraftRunner:
    """Отвечает за установку, настройку и запуск Minecraft."""
    def __init__(self, config, account_info=None, version=None, fabric_version=None, status_callback=None, progress_callback=None):
        self.config = config
        self.minecraft_directory = get_game_dir(config)
        self.account_info = account_info if account_info else {}
        self.java_settings = config.get('java_settings', {})
        self.version = version
        self.fabric_version = fabric_version
        self.status_callback = status_callback or (lambda text: None)
        self.progress_callback = progress_callback or (lambda value: None)
        self._java_path = None
        self._last_error = None
        self.authlib_path = get_authlib_path()

    def get_last_error(self):
        """Возвращает последнюю зафиксированную ошибку."""
        return self._last_error
    
    def set_versions(self, version, fabric_version):
        """Allows updating versions on an existing runner instance."""
        self.version = version
        self.fabric_version = fabric_version
        logger.info(f"Runner versions updated to MC: {version}, Fabric: {fabric_version}")
    
    def _status_handler(self, text):
        """Перехватывает и форматирует статусы от mll."""
        user_friendly_statuses = {
            "Install java runtime": "Установка среды Java...",
            "Download Assets": "Скачивание ресурсов игры...",
            "Download Libraries": "Скачивание библиотек...",
            "Running fabric installer": "Установка Fabric...",
            "Installation complete": "Установка завершена"
        }
        
        # Если статус есть в нашем словаре, отправляем его
        if text in user_friendly_statuses:
            self.status_callback(user_friendly_statuses[text])
        # Иначе, если это не спам про скачивание отдельных файлов, отправляем как есть
        elif not text.lower().startswith("download "):
            self.status_callback(text)

    def _find_java(self):
        """Ищет Java: сначала кастомный путь, потом системный, потом автопоиск."""
        custom_path = self.java_settings.get('path')
        if custom_path:
            if os.path.isfile(custom_path) and custom_path.endswith("javaw.exe"):
                return custom_path
            javaw = os.path.join(custom_path, "bin", "javaw.exe")
            if os.path.exists(javaw):
                return javaw

        system_java = shutil.which("javaw.exe")
        if system_java:
            return system_java

        auto_java = find_java_windows()
        if auto_java:
            return auto_java

        self._last_error = "Java не найдена. Установите Java 21+ или укажите путь в настройках."
        return None
        return None

    def validate_ely_token(self):
        """Проверка валидности токена Ely.by"""
        if self.account_info.get("type") == "ely.by":
            token = self.account_info.get("accessToken")
            if token:
                validate_url = "https://authserver.ely.by/auth/validate"
                try:
                    self.status_callback("Проверка токена авторизации...")
                    response = requests.post(validate_url, json={"accessToken": token}, timeout=10)
                    if response.status_code == 200:
                        logger.info("Токен Ely.by валиден")
                        return True
                    else:
                        logger.warning(f"Токен Ely.by невалиден, статус: {response.status_code}, тело: {response.text}")
                        self._last_error = "Токен авторизации истек. Необходимо войти в аккаунт заново."
                        return False
                except requests.exceptions.RequestException as e:
                    logger.error(f"Ошибка проверки токена Ely.by: {e}")
                    logger.info("Не удалось проверить токен из-за сетевой ошибки, продолжаем запуск")
                    return True
            else:
                self._last_error = "Отсутствует токен авторизации для аккаунта Ely.by"
                return False
        return True

    def _get_java_version_from_path(self, java_path):
        """Возвращает (major_version, full_version) или (None, ошибка)."""
        try:
            java_exe = java_path.replace("javaw.exe", "java.exe")
            if not os.path.exists(java_exe):
                java_exe = java_path

            result = subprocess.run(
                [java_exe, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            version_lines = (result.stderr or result.stdout or "").splitlines()
            version_line = version_lines[0] if version_lines else ''
            logger.info(f"Путь: {java_path}, java -version: {version_lines}")
            # Новый парсер: ищем версию между кавычками, потом после openjdk/java, потом просто первую цифру
            match = re.search(r'version\\s+\"([^\"]+)\"', version_line)
            if match:
                version_str = match.group(1)
                logger.info(f"Парсер: найдено по кавычкам: {version_str}")
            else:
                match = re.search(r'(?:openjdk|java)[^\d]*(\d+(?:\.\d+)+)', version_line, re.IGNORECASE)
                if match:
                    version_str = match.group(1)
                    logger.info(f"Парсер: найдено по openjdk/java: {version_str}")
                else:
                    match = re.search(r'(\d+)', version_line)
                    version_str = match.group(1) if match else version_line.strip() or "?"
                    logger.info(f"Парсер: найдено по первой цифре: {version_str}")
            # major_version — первая часть до точки
            try:
                major = int(version_str.split('.')[0])
            except Exception:
                return None, f"Не удалось определить major-версию из: {version_str}"
            return major, version_line.strip()

        except subprocess.TimeoutExpired:
            return None, "Таймаут при проверке Java"
        except Exception as e:
            return None, f"Ошибка при проверке версии: {str(e)}"

    def check_java_version_only(self):
        java_path = self._find_java()
        if not java_path:
            return False, self._last_error or "Java не найдена."

        major_version, full_version_str = self._get_java_version_from_path(java_path)
        if major_version is None:
            return False, full_version_str

        if major_version < 21:
            return False, f"Требуется Java 21+. Найдена версия {full_version_str}."

        self._java_path = java_path
        return True, f"Java {full_version_str} (≥ 21) найдена."

    def prepare_environment(self):
        """Проверяет наличие Java и валидность токена. Возвращает True в случае успеха, False если есть проблемы."""
        logger.info("--- Начало подготовки окружения ---")
        
        if self.account_info and not self.validate_ely_token():
            self.status_callback(f"Ошибка: {self._last_error}")
            logger.error(self._last_error)
            return False
        
        self.status_callback("Проверка среды Java...")
        is_valid, message = self.check_java_version_only()

        if not is_valid:
            self._last_error = message
            self.status_callback(f"Ошибка: {self._last_error}")
            return False
            
        logger.info(f"Используется Java по пути: {self._java_path}")
        return True

    def install_minecraft_dependencies(self):
        """Устанавливает ванильную версию Minecraft и Fabric."""
        if not self._java_path:
            raise RuntimeError("Путь к Java не определен. Вызовите prepare_environment() перед установкой.")
        if not self.minecraft_directory:
            raise RuntimeError("Путь к игре не определен. Невозможно установить зависимости.")

        callback = {"setStatus": self._status_handler, "setProgress": self.progress_callback}
        
        try:
            download_authlib_injector(self.authlib_path)
        except Exception as e:
            self._last_error = f"Ошибка загрузки authlib-injector: {e}"
            self.status_callback(self._last_error)
            raise RuntimeError("Не удалось подготовить среду для запуска Ely.by") from e

        if self.version:
            vanilla_version_path = os.path.join(self.minecraft_directory, "versions", self.version)
            is_installed = os.path.isdir(vanilla_version_path)

            if is_installed:
                logger.info(f"Minecraft {self.version} уже установлен, пропуск установки.")
                self.status_callback(f"Minecraft {self.version} уже установлен")
            else:
                logger.info(f"Установка Minecraft {self.version}...")
                mll.install.install_minecraft_version(self.version, self.minecraft_directory, callback=callback)
        else:
            raise ValueError("Версия Minecraft не указана, установка невозможна.")

        if self.fabric_version:
            fabric_version_id = f"fabric-loader-{self.fabric_version}-{self.version}"
            fabric_version_path = os.path.join(self.minecraft_directory, "versions", fabric_version_id)
            is_fabric_installed = os.path.isdir(fabric_version_path)

            if is_fabric_installed:
                logger.info(f"Fabric Loader {self.fabric_version} уже установлен, пропуск установки.")
                self.status_callback(f"Fabric Loader {self.fabric_version} уже установлен")
            else:
                logger.info(f"Установка Fabric Loader {self.fabric_version}...")
                
                original_path = os.environ.get('PATH', '')
                java_bin_dir = os.path.dirname(self._java_path)
                
                try:
                    os.environ['PATH'] = f"{java_bin_dir}{os.pathsep}{original_path}"
                    logger.info(f"Временно добавлен '{java_bin_dir}' в PATH для установщика Fabric.")
                    
                    mll.fabric.install_fabric(self.version, self.minecraft_directory, self.fabric_version, callback=callback)

                except Exception as e:
                    logger.error(f"Ошибка во время установки Fabric: {e}", exc_info=True)
                    self._last_error = f"Ошибка установки Fabric: {e}"
                    raise RuntimeError(self._last_error) from e
                finally:
                    os.environ['PATH'] = original_path
                    logger.info("Исходный PATH восстановлен.")

        logger.info("--- Подготовка окружения завершена ---")


    def run_only(self):
        """
        Только запускает игру, предполагая, что все файлы на месте.
        Теперь stdout/stderr Minecraft пишутся в .kristory/logs/minecraft.log
        """
        logger.info("--- Начало запуска игры ---")

        if not self.version:
            raise ValueError("Версия Minecraft не указана. Невозможно запустить игру.")
        
        if not self._java_path:
             raise RuntimeError("Путь к Java не был определён. Вызовите prepare_environment() перед запуском.")
             
        if not self.minecraft_directory:
             raise RuntimeError("Путь к игре не определён. Невозможно запустить.")

        version_id = f"fabric-loader-{self.fabric_version}-{self.version}" if self.fabric_version else self.version

        options = {}
        options["username"] = self.account_info.get("username")
        options["uuid"] = self.account_info.get("uuid")
        options["token"] = self.account_info.get("accessToken", "0") 
        options["gameDirectory"] = self.minecraft_directory
        options['executablePath'] = self._java_path
        
        jvm_arguments = []
        if self.java_settings.get('min_mem') and self.java_settings.get('max_mem'):
            jvm_arguments.extend([
                f"-Xms{self.java_settings['min_mem']}M",
                f"-Xmx{self.java_settings['max_mem']}M"
            ])

        if self.account_info.get("type") == "ely.by":
            if not os.path.exists(self.authlib_path):
                download_authlib_injector(self.authlib_path)
            jvm_arguments.extend([
                f"-javaagent:{self.authlib_path}=https://authserver.ely.by",
                "-Dely.auth.mojang=false"
            ])
        
        options["jvmArguments"] = jvm_arguments
        logger.info(f"Запуск версии: {version_id}")

        try:
            minecraft_command = mll.command.get_minecraft_command(version_id, self.minecraft_directory, options)
            
            if sys.platform == "win32" and minecraft_command[0].endswith("java.exe"):
                 javaw_path = os.path.join(os.path.dirname(minecraft_command[0]), "javaw.exe")
                 if os.path.exists(javaw_path):
                     logger.info("Переключение на javaw.exe для скрытия консоли.")
                     minecraft_command[0] = javaw_path
                 else:
                     logger.warning("javaw.exe не найден, может появиться консоль.")

        except Exception as e:
            logger.error(f"Ошибка при получении команды запуска: {e}", exc_info=True)
            self._last_error = f"Не удалось получить команду для версии {version_id}"
            raise RuntimeError(self._last_error) from e

        self.status_callback("Запускаем Minecraft...")
        logger.info(f"Команда запуска: {' '.join(minecraft_command)}")
        try:
            # --- Новый блок: логирование Minecraft ---
            from .paths import get_logs_dir
            logs_dir = get_logs_dir()
            os.makedirs(logs_dir, exist_ok=True)
            mc_log_path = os.path.join(logs_dir, "minecraft.log")
            mc_log_file = open(mc_log_path, "a", encoding="utf-8")
            return subprocess.Popen(
                minecraft_command,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                stdout=mc_log_file,
                stderr=subprocess.STDOUT,
                cwd=self.minecraft_directory
            )
        except Exception as e:
            self._last_error = f"Ошибка запуска: {e}"
            self.status_callback(self._last_error)
            logger.error(self._last_error, exc_info=True)
            return None
