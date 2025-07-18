import sys
import os
import json
import urllib.request
import subprocess
import ctypes
from ctypes import wintypes
import traceback
import threading
import logging
from pathlib import Path

# Настройка логирования
def setup_logging():
    try:
        log_dir = Path(__file__).parent / 'logs'
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / 'installer.log'
        
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        logger = logging.getLogger(__name__)
        logger.info("Logging initialized successfully")
        logger.info(f"Log file path: {log_file}")
        
        # Проверяем права доступа к файлу логов
        log_file.touch()
        logger.info("Successfully tested write access to log file")
        return logger
        
    except Exception as e:
        print(f"Critical error initializing logging: {e}")
        print("Continuing without logging...")
        logger = logging.getLogger(__name__)
        logger.addHandler(logging.StreamHandler())
        return logger

logger = setup_logging()

# PyQt6 импорты
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QProgressBar, 
                             QMessageBox, QLineEdit, QFileDialog)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPoint

# --- Конфигурация ---
GITHUB_REPO_OWNER = "rulled"
GITHUB_REPO_NAME = "kristory-launcher"
FULL_SETUP_ARTIFACT_NAME = "KRISTORY_Full_Setup"
LAUNCHER_EXE_NAME = "Kristory Launcher.exe"
APP_NAME = "Kristory Launcher"
LAUNCHER_FOLDER_NAME = "Kristory Launcher"
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 280

# --- Пути ---
TEMP_DOWNLOAD_DIR = Path(os.getenv('TEMP')) / 'KRISTORYInstaller'
DEFAULT_INSTALL_PATH = Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / LAUNCHER_FOLDER_NAME

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = Path(sys._MEIPASS) / 'public'
    except Exception:
        base_path = Path(__file__).parent.parent / 'public'
    
    return base_path / relative_path

def normalize_path(path):
    """Нормализация пути с правильными слешами для Windows"""
    return str(Path(path).resolve())

def ensure_launcher_folder(install_path):
    """Убеждаемся, что путь заканчивается на 'Kristory Launcher'"""
    path = Path(install_path)
    if path.name != LAUNCHER_FOLDER_NAME:
        path = path / LAUNCHER_FOLDER_NAME
    return str(path)

class Worker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    progress_updated = pyqtSignal(int)
    
    def __init__(self, install_path):
        super().__init__()
        self.install_path = Path(install_path)

    def run(self):
        setup_path = None
        try:
            # Поиск последней версии
            self.status_updated.emit("Поиск последней версии...")
            api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
            
            with urllib.request.urlopen(api_url, timeout=15) as response:
                if response.status != 200:
                    raise Exception(f"Ошибка API GitHub: {response.status}")
                release_data = json.loads(response.read().decode())
            
            # Поиск нужного артефакта
            asset_info = None
            for asset in release_data.get("assets", []):
                if asset["name"].startswith(FULL_SETUP_ARTIFACT_NAME):
                    asset_info = asset
                    break
            
            if not asset_info:
                raise Exception(f"Артефакт '{FULL_SETUP_ARTIFACT_NAME}*.exe' не найден.")
            
            download_url = asset_info["browser_download_url"]
            filename = asset_info["name"]
            total_size = asset_info["size"]
            
            # Создание временной директории
            TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)
            setup_path = TEMP_DOWNLOAD_DIR / filename
            
            # Скачивание установщика
            self.status_updated.emit("Скачивание установщика...")
            self._download_file(download_url, setup_path, total_size)
            
            # Установка
            self.status_updated.emit("Установка лаунчера...")
            self.progress_updated.emit(100)
            
            # Нормализация пути установки
            normalized_install_path = normalize_path(self.install_path)
            logger.info(f"Using installation path: {normalized_install_path}")
            
            # Проверка доступности установщика
            if not setup_path.exists():
                raise FileNotFoundError(f"Установщик не найден: {setup_path}")
            
            # Запуск установщика
            self._run_installer(setup_path, normalized_install_path)
            
            self.status_updated.emit("Установка завершена!")
            
            # Запуск лаунчера
            launcher_exe_path = Path(normalized_install_path) / LAUNCHER_EXE_NAME
            
            if not launcher_exe_path.exists():
                raise Exception(f"Не удалось найти {launcher_exe_path}.\n"
                              f"Проверьте права доступа к директории и наличие исполняемого файла.")
            
            # Запуск лаунчера в отдельном процессе
            subprocess.Popen([str(launcher_exe_path)], 
                           cwd=str(launcher_exe_path.parent),
                           creationflags=subprocess.DETACHED_PROCESS,
                           close_fds=True)
            
            self.finished.emit()
            
        except Exception as e:
            logger.error(f"Installation error: {e}")
            self.error.emit(f"{e}\n\nTraceback:\n{traceback.format_exc()}")
        finally:
            # Очистка временных файлов
            if setup_path and setup_path.exists():
                try:
                    setup_path.unlink()
                except OSError as e:
                    logger.warning(f"Could not remove temp file: {e}")

    def _download_file(self, url, output_path, total_size):
        """Скачивание файла с прогрессом"""
        downloaded_size = 0
        chunk_size = 8192
        
        with urllib.request.urlopen(url) as response, open(output_path, 'wb') as out_file:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded_size += len(chunk)
                percent = int((downloaded_size / total_size) * 100)
                self.progress_updated.emit(percent)

    def _run_installer(self, setup_path, install_path):
        """Запуск NSIS установщика"""
        install_command = [str(setup_path), '/S', f'/D={install_path}']
        
        self.status_updated.emit(f"Запуск установщика: {' '.join(install_command)}")
        
        try:
            result = subprocess.run(
                install_command,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=300,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Installation failed with code {result.returncode}")
                logger.error(f"Stdout: {result.stdout}")
                logger.error(f"Stderr: {result.stderr}")
                raise Exception(f"Установщик вернул код ошибки {result.returncode}.\n"
                              f"Stdout: {result.stdout}\n"
                              f"Stderr: {result.stderr}")
                              
        except subprocess.TimeoutExpired:
            raise Exception("Установщик не отвечает более 5 минут")
        except Exception as e:
            raise Exception(f"Ошибка при запуске установщика: {e}")

class DownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.old_pos = None
        self._setup_window()
        self._setup_ui()
        
    def _setup_window(self):
        """Настройка окна"""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowTitle(f"{APP_NAME} Installer")
        
        # Установка иконки
        try:
            icon_path = resource_path('icon.ico')
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception as e:
            logger.warning(f"Не удалось установить иконку: {e}")
            
        self._apply_window_effects()
        
    def _apply_window_effects(self):
        """Применение нативных эффектов Windows"""
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            dwmapi = ctypes.windll.dwmapi
            
            # Применение backdrop эффекта
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            value = wintypes.DWORD(2)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 
                                       ctypes.byref(value), ctypes.sizeof(value))
            
            # Скругление углов
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            value = wintypes.DWORD(2)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, 
                                       ctypes.byref(value), ctypes.sizeof(value))
                                       
        except Exception as e:
            logger.warning(f"Не удалось применить нативные эффекты Windows: {e}")

    def _setup_ui(self):
        """Настройка пользовательского интерфейса"""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        central_widget.setObjectName("CentralWidget")
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Заголовок
        self.title_bar = self._create_title_bar()
        
        # Основной контент
        content_widget = self._create_content_widget()
        
        main_layout.addWidget(self.title_bar)
        main_layout.addWidget(content_widget)
        
        self._apply_styles()

    def _create_title_bar(self):
        """Создание заголовка окна"""
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_layout = QHBoxLayout(title_bar)
        
        title_label = QLabel("KRISTORY INSTALLER")
        title_label.setObjectName("TitleLabel")
        
        close_button = QPushButton("✕")
        close_button.setObjectName("CloseButton")
        close_button.clicked.connect(self.close)
        
        title_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignLeft)
        title_layout.addStretch()
        title_layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        
        return title_bar

    def _create_content_widget(self):
        """Создание основного контента"""
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(40, 20, 40, 40)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Путь установки
        path_label = QLabel("Папка для установки лаунчера:")
        path_label.setObjectName("PathLabel")
        
        self.path_edit = QLineEdit(str(DEFAULT_INSTALL_PATH))
        self.path_edit.setObjectName("PathEdit")
        
        browse_button = QPushButton("Обзор...")
        browse_button.setObjectName("BrowseButton")
        browse_button.clicked.connect(self.browse_folder)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_button)
        
        # Кнопка установки
        self.install_button = QPushButton("Установить")
        self.install_button.setObjectName("InstallButton")
        self.install_button.clicked.connect(self.start_installation)
        
        # Статус и прогресс
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        
        # Компоновка
        content_layout.addStretch(2)
        content_layout.addWidget(path_label)
        content_layout.addLayout(path_layout)
        content_layout.addSpacing(20)
        content_layout.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignCenter)
        content_layout.addSpacing(15)
        content_layout.addWidget(self.status_label)
        content_layout.addWidget(self.progress_bar)
        content_layout.addStretch(1)
        
        return content_widget
    
    def browse_folder(self):
        """Выбор папки для установки"""
        current_path = Path(self.path_edit.text())
        base_directory = current_path.parent if current_path.name == LAUNCHER_FOLDER_NAME else current_path
        
        directory = QFileDialog.getExistingDirectory(
            self, 
            "Выберите папку для установки", 
            str(base_directory)
        )
        
        if directory:
            install_path = ensure_launcher_folder(directory)
            
            # Создаем папку если её нет
            try:
                Path(install_path).mkdir(parents=True, exist_ok=True)
                logger.info(f"Install path set to: {install_path}")
                self.path_edit.setText(install_path)
            except Exception as e:
                logger.error(f"Failed to create folder: {e}")
                QMessageBox.critical(
                    self, 
                    "Ошибка", 
                    f"Не удалось создать папку {install_path}.\nОшибка: {str(e)}"
                )

    def start_installation(self):
        """Начало установки"""
        install_path = self.path_edit.text().strip()
        
        if not install_path:
            QMessageBox.warning(self, "Ошибка", "Путь установки не может быть пустым.")
            return
        
        # Убеждаемся, что путь заканчивается на папку лаунчера
        install_path = ensure_launcher_folder(install_path)
        install_path_obj = Path(install_path)
        
        logger.info(f"Starting installation with path: {install_path}")
        
        # Проверка родительской директории
        parent_dir = install_path_obj.parent
        if not parent_dir.exists():
            QMessageBox.critical(
                self, 
                "Ошибка", 
                f"Родительская папка {parent_dir} не существует.\n"
                "Пожалуйста, выберите существующую папку."
            )
            return
            
        if not os.access(str(parent_dir), os.W_OK):
            QMessageBox.critical(
                self, 
                "Ошибка", 
                f"Нет прав на запись в папку {parent_dir}.\n"
                "Пожалуйста, выберите другую папку или запустите от имени администратора."
            )
            return
        
        # Создание папки установки
        try:
            install_path_obj.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Ошибка", 
                f"Не удалось создать папку установки: {e}"
            )
            return
            
        logger.info(f"Validated installation path: {install_path}")
        
        # Запуск установки
        self.install_button.setEnabled(False)
        self.progress_bar.show()
        
        self.thread = QThread()
        self.worker = Worker(install_path)
        self.worker.moveToThread(self.thread)
        
        # Подключение сигналов
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_installation_finished)
        self.worker.error.connect(self.on_installation_error)
        self.worker.status_updated.connect(self.status_label.setText)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        
        # Очистка
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        
        self.thread.start()

    def on_installation_finished(self):
        """Обработка успешной установки"""
        install_path = self.path_edit.text()
        QMessageBox.information(
            self, 
            "Установка", 
            f"Лаунчер успешно установлен и будет запущен из:\n{install_path}"
        )
        self.close()

    def on_installation_error(self, error_msg):
        """Обработка ошибки установки"""
        QMessageBox.critical(self, "Ошибка установки", f"Произошла ошибка:\n{error_msg}")
        self.install_button.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("")

    def _apply_styles(self):
        """Применение стилей"""
        self.setStyleSheet("""
            #CentralWidget {
                background-color: #26152D;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            #TitleLabel {
                color: #E5E7EB;
                font-size: 14px;
                font-family: "Segoe UI", sans-serif;
                font-weight: bold;
                padding-left: 20px;
            }
            #CloseButton {
                color: #E5E7EB;
                font-family: "Segoe UI", sans-serif;
                font-size: 16px;
                background-color: transparent;
                border: none;
                padding: 5px 15px;
            }
            #CloseButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            #InstallButton {
                background-color: #A24BE0;
                color: white;
                font-size: 16px;
                font-weight: bold;
                font-family: "Segoe UI", sans-serif;
                padding: 12px 60px;
                border-radius: 8px;
                border: none;
            }
            #InstallButton:hover {
                background-color: #8E3FD3;
            }
            #InstallButton:disabled {
                background-color: #512863;
                color: #D6C2EF;
            }
            #StatusLabel {
                color: #D6C2EF;
                font-size: 13px;
                font-family: "Segoe UI", sans-serif;
                min-height: 18px;
            }
            #PathLabel {
                color: #E5E7EB;
                font-size: 14px;
                margin-bottom: 8px;
                font-family: "Segoe UI", sans-serif;
            }
            #PathEdit {
                background-color: rgba(0,0,0,0.3);
                border: 1px solid #9B59B6;
                border-radius: 6px;
                padding: 8px;
                color: #E5E7EB;
                font-family: "Segoe UI", sans-serif;
            }
            #BrowseButton {
                background-color: #512863;
                color: white;
                border: 1px solid #9B59B6;
                border-radius: 6px;
                padding: 8px 12px;
                font-family: "Segoe UI", sans-serif;
            }
            #BrowseButton:hover {
                background-color: #613872;
            }
            #ProgressBar {
                min-height: 6px;
                max-height: 6px;
                border-radius: 3px;
                background-color: #512863;
            }
            #ProgressBar::chunk {
                background-color: #A24BE0;
                border-radius: 3px;
            }
        """)

    # Обработка событий мыши для перетаскивания окна
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 40:
            self.old_pos = event.globalPosition().toPoint()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None

    def mouseMoveEvent(self, event):
        if not self.old_pos:
            return
        delta = QPoint(event.globalPosition().toPoint() - self.old_pos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPosition().toPoint()

def is_admin():
    """Проверка на права администратора"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def main():
    """Основная функция"""
    if is_admin():
        app = QApplication(sys.argv)
        window = DownloaderApp()
        window.show()
        sys.exit(app.exec())
    else:
        # Перезапуск с правами администратора
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )

if __name__ == "__main__":
    main()