
import os
import sys
import json
import uuid
import threading
import logging
import zipfile
import requests
import io
import shutil
import psutil # Added for system info
import subprocess
from PIL import Image
from werkzeug.utils import secure_filename
from mcstatus import JavaServer
import time # Added for log rotation timestamp
from datetime import datetime # More specific import for timestamp format
import glob

from flask import Flask, jsonify, request, abort, send_file
from flask_cors import CORS

from .minecraft import MinecraftRunner
from .mod_manager import ModManager
from .update_manager import check_github_for_updates, download_file, install_modpack, get_local_version
from .paths import (
    get_data_dir, get_config_path, get_renders_dir,
    get_mods_dir, ensure_directories_exist, get_initial_config_path, get_game_dir
)
# Удалён импорт IntegrityChecker


# --- Configuration & Constants ---
# ensure_directories_exist() is now called after loading config to get the correct path

STEVE_SKIN_URL = "https://crafatar.com/skins/8667ba71-b85a-4004-a454-48534ac7a785"
ELY_BY_AUTH_URL = "https://authserver.ely.by/auth/authenticate"
SKIN_RENDER_SCALE = 10
REQUEST_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)
http_session = requests.Session()

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "http://localhost:9002"}})

# --- Logging Setup ---
def setup_logging(is_debug_mode=False):
    """Configures the application's logging, creating a new timestamped log file for each session."""
    config = load_config()  # Получаем конфиг
    logs_dir = os.path.join(get_data_dir(), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Generate a unique filename for this session using a timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file_path = os.path.join(logs_dir, f'launcher_{timestamp}.log')

    log_level = logging.INFO # Default
    try:
        if is_debug_mode:
            log_level = logging.DEBUG
        else:
            log_level = logging.DEBUG if config.get('game_settings', {}).get('enable_logs') else logging.INFO
    except Exception as e:
        print(f"Warning: Could not load config for logging setup. Defaulting to INFO. Error: {e}")
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)-15s - %(levelname)-8s - %(message)s',
        handlers=[
            logging.FileHandler(log_file_path, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logger.info(f"Logging configured with level: {logging.getLevelName(log_level)}. Log file: {log_file_path}")


# --- State Management Class ---
class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.is_processing = False
        self.status_text = "Ready"
        self.progress = 0
        self.version_info = {"minecraft": "N/A", "fabric": "N/A"}
        self.is_game_installed = False
        self.build_tag = None  # Новое поле для версии сборки

    def get_all(self):
        with self._lock:
            config = load_config()
            build_tag = config.get('current_build_tag')
            return {
                "is_processing": self.is_processing,
                "status_text": self.status_text,
                "progress": self.progress,
                "version_info": self.version_info,
                "is_game_installed": self.is_game_installed,
                "build_tag": build_tag,
            }

    def start_processing(self, initial_status="Starting..."):
        with self._lock:
            if self.is_processing:
                return False
            self.is_processing = True
            self.status_text = initial_status
            self.progress = 0
            return True

    def finish_processing(self, final_status="Ready"):
        with self._lock:
            self.is_processing = False
            self.status_text = final_status
            self.progress = 0

    def set_status(self, text):
        with self._lock:
            self.status_text = text
        logging.info(f"STATUS: {text}")

    def set_progress(self, progress_float):
        with self._lock:
            self.progress = int(progress_float * 100)
    
    def set_version_info(self, versions):
        with self._lock:
            if versions:
                self.version_info = versions

    def set_installed_status(self, installed):
        with self._lock:
            self.is_game_installed = installed

app_state = AppState()

# --- Helper Functions ---
def _get_default_java_settings():
    """Calculates smart default RAM settings based on system memory."""
    try:
        total_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        # 40% of total RAM
        default_max_ram = total_ram_mb * 0.4
        # Clamp between 2GB and 8GB
        default_max_ram = max(2048, min(default_max_ram, 8192))
        # Round to nearest 512MB
        rounded_max_ram = round(default_max_ram / 512) * 512
        default_min_ram = 1024
        logger.info(f"System RAM: {total_ram_mb}MB. Calculated default RAM allocation: min={default_min_ram}MB, max={rounded_max_ram}MB")
        return {'path': '', 'min_mem': default_min_ram, 'max_mem': rounded_max_ram}
    except Exception as e:
        logger.error(f"Could not get system RAM for default settings, falling back to static values. Error: {e}")
        return {'path': '', 'min_mem': 1024, 'max_mem': 4096}


# --- Config Management ---
def save_config(config_data):
    """Saves config and creates a backup of the previous one."""
    config_path = get_config_path()
    backup_path = config_path + '.bak'
    try:
        # Create backup
        if os.path.exists(config_path):
            shutil.copy2(config_path, backup_path)
            logger.info(f"Config backup created at {backup_path}")
        logger.info(f"[save_config] Сохраняю конфиг в: {config_path}")
        logger.debug(f"[save_config] Ключи для сохранения: {list(config_data.keys())}")
        # Save new config
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        logger.info("Configuration saved successfully.")
    except (IOError, shutil.Error) as e:
        logger.error(f"Error saving config: {e}")


def load_config():
    """
    Loads, validates, and repairs the config file.
    Tries to restore from backup if the main config is invalid.
    """
    config_path = get_config_path()
    
    default_config = {
        'clientToken': str(uuid.uuid4()),
        'accounts': [],
        'java_settings': {}, # Initially empty, calculated on demand
        'game_settings': { 
            'server_address': 'portal-1.nodes.hyprr.space:5032', 
            'enable_logs': False,
            'game_directory': '' # Empty means not set
        },
        'current_build_tag': None,
        'current_mrpack_filename': None,
        'last_selected_uuid': None
    }
    
    def _create_new_config():
        """Creates and saves a completely new default config."""
        logging.warning("Creating a new default configuration file.")
        new_config = default_config.copy()
        new_config['java_settings'] = _get_default_java_settings()
        save_config(new_config)
        return new_config

    def _read_and_parse_config(path):
        """Attempts to read and parse a JSON file."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content:
                logging.warning(f"Config file is empty: {path}")
                return None
            config = json.loads(content)
            if not isinstance(config, dict):
                logging.error(f"Config file content is not a dictionary: {path}")
                return None
            return config
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Error parsing config file {path}: {e}")
            return None

    # 1. Try to load the main config file
    config = _read_and_parse_config(config_path)

    # 2. If main config fails, try the backup
    if not config:
        logging.warning("Main config is invalid or missing, trying backup...")
        backup_path = config_path + '.bak'
        config = _read_and_parse_config(backup_path)
        if config:
            logging.info("Successfully loaded from backup. Restoring...")
            save_config(config) # This will save it back to the main file and re-create backup
        else:
            logging.warning("Backup config is also invalid or missing.")
            return _create_new_config()

    # 3. If loaded successfully, ensure all keys are present
    needs_save = False
    
    merge_defaults = {
        'clientToken': str(uuid.uuid4()),
        'accounts': [],
        'game_settings': { 
            'server_address': 'portal-1.nodes.hyprr.space:5032', 
            'enable_logs': False,
            'game_directory': ''
        },
        'current_build_tag': None,
        'current_mrpack_filename': None,
        'last_selected_uuid': None
    }

    for key, value in merge_defaults.items():
        if key not in config:
            config[key] = value
            needs_save = True
        elif isinstance(value, dict):
            if not isinstance(config.get(key), dict):
                config[key] = value
                needs_save = True
            else:
                for sub_key, sub_value in value.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = sub_value
                        needs_save = True
    
    # Handle java_settings separately
    if 'java_settings' not in config or not isinstance(config.get('java_settings'), dict) or not config['java_settings']:
        config['java_settings'] = _get_default_java_settings()
        needs_save = True
    else:
        # Check for individual keys without recalculating unless necessary
        java_defaults_template = {'path': '', 'min_mem': 1024, 'max_mem': 4096}
        is_java_config_ok = all(sub_key in config['java_settings'] for sub_key in java_defaults_template)
        if not is_java_config_ok:
            # Only recalculate if a key is missing
            default_java = _get_default_java_settings()
            for key, val in default_java.items():
                config['java_settings'].setdefault(key, val)
            needs_save = True

    if needs_save:
        logging.info("Config was missing keys, defaults have been added. Saving.")
        save_config(config)

    return config


# --- Skin Rendering ---
def render_skin_front_view(skin_image: Image.Image) -> Image.Image:
    scale = SKIN_RENDER_SCALE
    if skin_image.mode != 'RGBA': skin_image = skin_image.convert('RGBA')
    if skin_image.size != (64, 64):
        old_skin = skin_image.copy()
        skin_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        skin_image.paste(old_skin, (0, 0))
    is_legacy = skin_image.getpixel((0, 32))[3] == 0
    assembled = Image.new('RGBA', (16, 32), (0, 0, 0, 0))
    part_coords = { 'head': (8, 8, 16, 16), 'torso': (20, 20, 28, 32), 'r_arm': (44, 20, 48, 32), 'r_leg': (4, 20, 8, 32), 'l_arm': (36, 52, 40, 64), 'l_leg': (20, 52, 24, 64), 'head_ov': (40, 8, 48, 16), 'torso_ov': (20, 36, 28, 48), 'r_arm_ov': (44, 36, 48, 48), 'r_leg_ov': (4, 36, 8, 48), 'l_arm_ov': (52, 52, 56, 64), 'l_leg_ov': (4, 52, 8, 64) }
    head = skin_image.crop(part_coords['head']); torso = skin_image.crop(part_coords['torso']); r_arm = skin_image.crop(part_coords['r_arm']); r_leg = skin_image.crop(part_coords['r_leg']); l_arm = skin_image.crop(part_coords['l_arm']) if not is_legacy else r_arm.transpose(Image.Transpose.FLIP_LEFT_RIGHT); l_leg = skin_image.crop(part_coords['l_leg']) if not is_legacy else r_leg.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    assembled.paste(head, (4, 0)); assembled.paste(torso, (4, 8)); assembled.paste(l_arm, (0, 8)); assembled.paste(r_arm, (12, 8)); assembled.paste(l_leg, (4, 20)); assembled.paste(r_leg, (8, 20))
    head_ov = skin_image.crop(part_coords['head_ov'])
    if not is_legacy:
        torso_ov = skin_image.crop(part_coords['torso_ov']); r_arm_ov = skin_image.crop(part_coords['r_arm_ov']); r_leg_ov = skin_image.crop(part_coords['r_leg_ov']); l_arm_ov = skin_image.crop(part_coords['l_arm_ov']); l_leg_ov = skin_image.crop(part_coords['l_leg_ov'])
        assembled.paste(torso_ov, (4, 8), torso_ov); assembled.paste(l_arm_ov, (0, 8), l_arm_ov); assembled.paste(r_arm_ov, (12, 8), r_arm_ov); assembled.paste(l_leg_ov, (4, 20), l_leg_ov); assembled.paste(r_leg_ov, (8, 20), r_leg_ov)
    assembled.paste(head_ov, (4, 0), head_ov)
    return assembled.resize((16 * scale, 32 * scale), Image.Resampling.NEAREST)

# --- Helper Functions ---
def _get_mrpack_path(config):
    game_dir = get_game_dir(config)
    if not game_dir: return None # If game dir is not set, no mrpack can exist
    filename = config.get('current_mrpack_filename')
    if filename:
        path = os.path.join(game_dir, filename)
        if os.path.exists(path): return path
    # Fallback to searching the directory
    for f in os.listdir(game_dir):
        if f.endswith(".mrpack"): return os.path.join(game_dir, f)
    return None

def _is_game_installed():
    config = load_config()
    game_dir = get_game_dir(config)
    if not game_dir: return False
    return os.path.exists(os.path.join(game_dir, "versions"))

def _is_installation_valid(config):
    game_dir = get_game_dir(config)
    if not game_dir:
        return False

    # --- Новая логика: сравниваем тег релиза ---
    try:
        local_tag = get_local_version(config)
        update_info = check_github_for_updates()
        remote_tag = update_info['tag'] if update_info else None
        if not local_tag or not remote_tag:
            logger.info(f"Не удалось определить локальный или удалённый тег: local={local_tag}, remote={remote_tag}")
            return False
        if local_tag != remote_tag:
            logger.info(f"Тег релиза отличается: local={local_tag}, remote={remote_tag}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при сравнении тегов релиза: {e}")
        return False

    # --- Старая логика: сравниваем .version (MC/Fabric) ---
    version_file = os.path.join(game_dir, ".version")
    if not os.path.exists(version_file): return False
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.exists(versions_dir) or len(os.listdir(versions_dir)) == 0: return False
    try:
        with open(version_file, 'r') as f:
            local_version = f.read().strip()
        mrpack_path = _get_mrpack_path(config)
        if mrpack_path and os.path.exists(mrpack_path):
            versions = _get_versions_from_mrpack(config)
            if not versions: return False # If mrpack is invalid, force reinstall
            expected_version = f"{versions.get('minecraft', 'unknown')}-{versions.get('fabric', 'unknown')}"
            return local_version == expected_version
    except Exception as e:
        logger.error(f"Ошибка проверки версии: {e}")
        return False
    return True

def _save_installation_version(config):
    game_dir = get_game_dir(config)
    if not game_dir: return
    try:
        versions = _get_versions_from_mrpack(config)
        version_string = f"{versions.get('minecraft', 'unknown')}-{versions.get('fabric', 'unknown')}"
        version_file = os.path.join(game_dir, ".version")
        with open(version_file, 'w') as f: f.write(version_string)
        logger.info(f"Сохранена версия установки: {version_string}")
    except Exception as e:
        logger.error(f"Ошибка сохранения версии: {e}")

def _get_versions_from_mrpack(config):
    mrpack_path = _get_mrpack_path(config)
    if not mrpack_path: return None
    try:
        with zipfile.ZipFile(mrpack_path, 'r') as mrpack:
            with mrpack.open('modrinth.index.json') as index_file:
                index_data = json.load(index_file)
                return {'minecraft': index_data['dependencies']['minecraft'], 'fabric': index_data['dependencies'].get('fabric-loader') or index_data['dependencies'].get('forge')}
    except Exception as e:
        logging.error(f"Error reading .mrpack file {mrpack_path}: {e}")
    return None

def update_version_info_in_state(config):
    versions = _get_versions_from_mrpack(config)
    app_state.set_version_info(versions)

# --- API Endpoints ---

@app.route('/api/open-logs', methods=['GET'])
def open_logs_directory():
    """Ensures logs directory exists and returns its path."""
    try:
        logs_dir = os.path.join(get_data_dir(), 'logs')
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir, exist_ok=True)
            # Create a placeholder file to ensure directory is not empty
            with open(os.path.join(logs_dir, 'placeholder.txt'), 'w', encoding='utf-8') as f:
                f.write('This directory contains launcher logs.')
        return jsonify({"path": logs_dir}), 200
    except Exception as e:
        logger.error(f"Error opening logs directory: {e}")
        return jsonify({"error": f"Failed to open logs directory: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    config = load_config()
    update_version_info_in_state(config)
    app_state.set_installed_status(_is_game_installed())
    return jsonify(app_state.get_all())

@app.route('/api/config', methods=['GET', 'POST', 'PATCH'])
def config_endpoint():
    if request.method == 'GET':
        config = load_config()
        return jsonify(config)
    else:
        config = load_config()
        updates = request.get_json(force=True)
        logger.debug(f"CONFIG BEFORE UPDATE: {config}")
        logger.debug(f"UPDATES: {updates}")
        if not updates:
            return jsonify({'error': 'No data provided'}), 400
        # --- apply updates ---
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        logger.info(f"Game settings updated via API: {config.get('game_settings')}")
        save_config(config)
        # --- ГАРАНТИРУЕМ создание папки клиента ---
        if get_game_dir(config):
            ensure_directories_exist(config)
        return jsonify(config)

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    config = load_config()
    return jsonify(config.get('accounts', []))

@app.route('/api/accounts/<account_uuid>', methods=['DELETE'])
def delete_account(account_uuid):
    config = load_config()
    try: uuid.UUID(account_uuid)
    except ValueError: abort(400, "Invalid UUID format")
    
    accounts = config.get('accounts', [])
    initial_len = len(accounts)
    accounts = [acc for acc in accounts if acc['uuid'] != account_uuid]
    if len(accounts) == initial_len: abort(404, "Account not found")
    config['accounts'] = accounts
    if config.get('last_selected_uuid') == account_uuid: config['last_selected_uuid'] = accounts[0]['uuid'] if accounts else None
    
    renders_dir = get_renders_dir()
    render_path = os.path.join(renders_dir, f"{account_uuid}.png")
    try:
        if os.path.exists(render_path): os.remove(render_path)
    except OSError as e:
        logging.warning(f"Could not delete render for {account_uuid}: {e}")
        
    save_config(config)
    logger.info(f"Account {account_uuid} removed successfully.")
    return jsonify({"message": "Account removed successfully"})

@app.route('/api/auth/elyby', methods=['POST'])
def auth_elyby():
    config = load_config()
    data = request.json
    email, password = data.get('email'), data.get('password')
    if not email or not password: abort(400, "Email and password are required")
    logger.info(f"Попытка логина Ely.by для email: {email}")
    client_token = config.get('clientToken')
    payload = {"agent": {"name": "Minecraft", "version": 1}, "username": email, "password": password, "clientToken": client_token, "requestUser": True}
    try:
        response = http_session.post(ELY_BY_AUTH_URL, json=payload, timeout=15)
        logger.info(f"Ответ Ely.by: status={response.status_code}")
        if response.status_code != 200:
            logger.error(f"Ошибка авторизации Ely.by: status={response.status_code}, text={response.text}")
            try:
                error_data = response.json()
                error_msg = error_data.get('errorMessage', 'Unknown authentication error')
                if "Account protected with two factor auth" in error_msg: return jsonify({'error': 'Аккаунт защищен 2FA. Введите пароль в формате "пароль:токен"'}), 401
                return jsonify({'error': error_msg}), response.status_code
            except json.JSONDecodeError:
                return jsonify({'error': f'Authentication failed with status {response.status_code}. Ответ: {response.text}'}), response.status_code
        auth_data = response.json()
        logger.info(f"Успешный ответ Ely.by: {auth_data}")
        if not all(k in auth_data for k in ['selectedProfile', 'accessToken', 'clientToken']) or not all(k in auth_data.get('selectedProfile', {}) for k in ['id', 'name']):
            logger.error(f"Ely.by auth response is malformed: {auth_data}")
            return jsonify({'error': 'Получен неверный ответ от сервера авторизации.'}), 500
        account_data = {'type': 'ely.by', 'username': auth_data['selectedProfile']['name'], 'uuid': auth_data['selectedProfile']['id'], 'accessToken': auth_data['accessToken'], 'clientToken': auth_data['clientToken']}
        accounts = config.get('accounts', [])
        if any(acc['uuid'] == account_data['uuid'] for acc in accounts): return jsonify({'error': 'Этот аккаунт уже добавлен.'}), 409
        skin_url = f"http://skinsystem.ely.by/skins/{account_data['username']}.png"
        logger.info(f"Пробую скачать и отрендерить скин для {account_data['username']} ({account_data['uuid']})")
        _render_and_cache_skin(skin_url, account_data['uuid'])
        accounts.append(account_data)
        config['accounts'] = accounts
        if len(accounts) == 1 or not config.get('last_selected_uuid'): config['last_selected_uuid'] = account_data['uuid']
        save_config(config)
        logger.info(f"Account added successfully: {account_data['username']} ({account_data['uuid']})")
        return jsonify(account_data), 201
    except requests.exceptions.RequestException as e:
        logger.error(f"Ely.by auth network error: {e}")
        return jsonify({'error': f'Ошибка сети при подключении к Ely.by: {e}'}), 500

# --- Skin Rendering ---
def _get_renders_dir_safe(config=None):
    return get_renders_dir()

def _render_and_cache_skin(skin_url, user_uuid):
    renders_dir = get_renders_dir()
    os.makedirs(renders_dir, exist_ok=True)
    try:
        logger.info(f"Пробую скачать скин по адресу: {skin_url} для UUID: {user_uuid}")
        skin_response = http_session.get(skin_url, stream=True, allow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS)
        skin_response.raise_for_status()
        with Image.open(io.BytesIO(skin_response.content)) as skin_image:
            rendered_skin = render_skin_front_view(skin_image)
            render_path = os.path.join(renders_dir, f"{user_uuid}.png")
            rendered_skin.save(render_path, "PNG")
            logger.info(f"Rendered and cached skin for UUID {user_uuid} at {render_path}")
    except Exception as e:
        logger.error(f"Could not download or render skin for UUID {user_uuid} from {skin_url}: {e}")

@app.route('/api/skin/<user_uuid>', methods=['GET'])
def get_rendered_skin(user_uuid):
    renders_dir = get_renders_dir()
    render_path = os.path.join(renders_dir, f"{user_uuid}.png")
    if os.path.exists(render_path): 
        logger.info(f"Отдаю скин для UUID {user_uuid} из {render_path}")
        return send_file(render_path, mimetype='image/png')
    logger.warning(f"Rendered skin for {user_uuid} not found in '{renders_dir}'. Serving fallback Steve.")
    try:
        logger.info(f"Пробую скачать дефолтный скин Steve: {STEVE_SKIN_URL}")
        skin_response = http_session.get(STEVE_SKIN_URL, stream=True, timeout=REQUEST_TIMEOUT_SECONDS)
        skin_response.raise_for_status()
        with Image.open(io.BytesIO(skin_response.content)) as skin_image:
            rendered_skin = render_skin_front_view(skin_image)
            img_io = io.BytesIO()
            rendered_skin.save(img_io, 'PNG')
            img_io.seek(0)
            logger.info(f"Отдаю fallback Steve skin для UUID {user_uuid}")
            return send_file(img_io, mimetype='image/png')
    except Exception as e:
        logger.error(f"Could not serve fallback Steve skin: {e}")
        abort(404, "Rendered skin not found and fallback failed.")

@app.route('/api/server-status', methods=['GET'])
def get_server_status():
    config = load_config()
    address = config.get('game_settings', {}).get('server_address')
    if not address: return jsonify({'online': False, 'error': 'Server address not configured.'})
    try:
        server = JavaServer.lookup(address, timeout=5)
        status = server.status()
        return jsonify({'online': True, 'version': status.version.name, 'players_online': status.players.online, 'players_max': status.players.max, 'latency': status.latency})
    except Exception as e:
        logging.warning(f"Failed to get server status for {address}: {e}")
        return jsonify({'online': False})

@app.route('/api/system-info', methods=['GET'])
def get_system_info():
    try:
        mem = psutil.virtual_memory()
        total_ram_mb = mem.total // (1024 * 1024)
        return jsonify({'total_ram_mb': total_ram_mb})
    except Exception as e:
        logging.error(f"Could not get system RAM info: {e}")
        return jsonify({'total_ram_mb': 8192})

def check_system_java():
    import shutil, subprocess, re
    java_path = shutil.which("javaw.exe") or shutil.which("java.exe")
    if not java_path:
        return False, "Java не найдена. Установите Java 21+."
    try:
        result = subprocess.run([java_path, "-version"], capture_output=True, text=True, timeout=5)
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
        try:
            major = int(version_str.split('.')[0])
        except Exception:
            return False, f"Не удалось определить major-версию из: {version_str}"
        if major < 21:
            return False, f"Требуется Java 21+. Найдена версия {version_line.strip()}."
        return True, f"Java {version_line.strip()} (≥ 21) найдена."
    except Exception as e:
        return False, f"Ошибка при проверке Java: {e}"

@app.route('/api/check-java', methods=['GET'])
def check_java_version():
    try:
        config = load_config()
        game_dir = config.get('game_settings', {}).get('game_directory')
        if not game_dir:
            is_valid, message = check_system_java()
            if not is_valid:
                return jsonify({"error": message}), 400
            return jsonify({"message": message}), 200
        runner = MinecraftRunner(config=config)
        is_valid, message = runner.check_java_version_only()
        if not is_valid:
            return jsonify({"error": message}), 400
        return jsonify({"message": message}), 200
    except Exception as e:
        logger.exception("Ошибка при проверке Java")
        return jsonify({"error": f"Ошибка при проверке Java: {e}"}), 500

@app.route('/api/java/detect', methods=['GET'])
def detect_java():
    """Автоматически ищет Java и возвращает результат фронту."""
    from .minecraft import MinecraftRunner
    config = load_config()
    runner = MinecraftRunner(config=config)
    is_valid, message = runner.check_java_version_only()
    
    if is_valid:
        return jsonify({"found": True, "message": message})
    else:
        return jsonify({"found": False, "message": message})

@app.route('/api/java/list', methods=['GET'])
def list_java_versions():
    import shutil, subprocess, re, os, glob
    java_candidates = set()
    results = []
    # 1. Все javaw.exe и java.exe из ВСЕХ путей PATH
    path_env = os.environ.get("PATH", "")
    for dir_path in path_env.split(";"):
        dir_path = dir_path.strip('"')
        for exe in ["javaw.exe", "java.exe"]:
            java_path = os.path.join(dir_path, exe)
            if os.path.isfile(java_path):
                java_candidates.add(os.path.abspath(java_path))
    # 2. Если ничего не найдено в PATH, ищем по стандартным папкам
    if not java_candidates:
        search_patterns = [
            r"%ProgramFiles%\Java\jdk-*\bin\javaw.exe",
            r"%ProgramFiles%\Java\jdk-*\bin\java.exe",
            r"%ProgramFiles%\Eclipse Adoptium\jdk-*\bin\javaw.exe",
            r"%ProgramFiles%\Eclipse Adoptium\jdk-*\bin\java.exe",
            r"%ProgramFiles%\Microsoft\jdk-*\bin\javaw.exe",
            r"%ProgramFiles%\Microsoft\jdk-*\bin\java.exe",
            r"%ProgramFiles(x86)%\Java\jdk-*\bin\javaw.exe",
            r"%ProgramFiles(x86)%\Java\jdk-*\bin\java.exe",
            r"C:\\Program Files\\Zulu\\zulu-*\\bin\\javaw.exe",
            r"C:\\Program Files\\Zulu\\zulu-*\\bin\\java.exe",
            r"C:\\Program Files\\Zulu\\zulu-24\\bin\\javaw.exe",
            r"C:\\Program Files\\Zulu\\zulu-24\\bin\\java.exe",
        ]
        for pattern in search_patterns:
            expanded = os.path.expandvars(pattern)
            for found in glob.glob(expanded):
                java_candidates.add(os.path.abspath(found))
    # 3. Убираем дубли из одной папки (оставляем только javaw.exe если есть)
    unique_dirs = {}
    for path in java_candidates:
        dir_path = os.path.dirname(path)
        if dir_path not in unique_dirs:
            unique_dirs[dir_path] = path
        else:
            # Если уже есть java.exe, а сейчас нашли javaw.exe — заменить на javaw.exe
            if path.endswith('javaw.exe'):
                unique_dirs[dir_path] = path
    filtered_candidates = set(unique_dirs.values())
    logger.info(f"Найдено кандидатов Java: {filtered_candidates}")
    # 4. Проверяем версии
    for java_path in sorted(filtered_candidates):
        try:
            result = subprocess.run([java_path, "-version"], capture_output=True, text=True, timeout=5)
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
            version_display = f"Java {version_str}"
        except Exception as e:
            version_display = f"Ошибка: {e}"
            logger.error(f"Ошибка при определении версии Java для {java_path}: {e}")
        # Проверяем, есть ли этот путь в PATH
        is_in_path = False
        for dir_path in path_env.split(";"):
            dir_path = dir_path.strip('"')
            if os.path.abspath(os.path.dirname(java_path)) == os.path.abspath(dir_path):
                is_in_path = True
                break
        results.append({
            "path": java_path,
            "version": version_display,
            "is_in_path": is_in_path
        })
    logger.info(f"Результаты поиска Java: {results}")
    return jsonify(results)

# --- Background Task Management ---
def _run_task_in_background(target_func, args_tuple):
    if not app_state.start_processing():
        abort(429, "Another process is already running")
    thread = threading.Thread(target=target_func, args=args_tuple)
    thread.daemon = True
    thread.start()
    return jsonify({"message": "Process started"})

@app.route('/api/launch', methods=['POST'])
def launch_game():
    selected_account_uuid = request.json.get('selected_account_uuid')
    if not selected_account_uuid: abort(400, "No account selected")
    try: uuid.UUID(selected_account_uuid)
    except ValueError: abort(400, "Invalid account UUID format")
    config = load_config()
    account = next((acc for acc in config['accounts'] if acc['uuid'] == selected_account_uuid), None)
    if not account: abort(404, "Selected account not found")
    return _run_task_in_background(_threaded_launch, (account, config))

@app.route('/api/verify-files', methods=['POST'])
def verify_files():
    config = load_config()
    # --- ГАРАНТИРУЕМ создание папки клиента ---
    game_dir = get_game_dir(config)
    if not game_dir:
        return jsonify({"error": "Папка для игры не выбрана. Проверка невозможна."}), 400
    ensure_directories_exist(config)
    
    return _run_task_in_background(_threaded_verify, (config,))

def _threaded_generic_install(config, runner: MinecraftRunner):
    game_dir = get_game_dir(config)
    if not game_dir:
        raise RuntimeError("Game directory not set. Cannot install.")

    from .update_manager import get_local_version, check_incremental_update
    app_state.set_status("Проверка обновлений сборки...")
    update_info = check_github_for_updates()
    current_build_tag = config.get('current_build_tag')
    local_mrpack_path = _get_mrpack_path(config)
    local_version = get_local_version(config)
    remote_version = update_info['tag'] if update_info else None
    update_type = check_incremental_update(local_version, remote_version)
    logger.info(f"Локальная версия: {local_version}, удаленная: {remote_version}, тип обновления: {update_type}")
    if update_info and (update_info['tag'] != current_build_tag or not local_mrpack_path or update_type != "none"):
        reason = "новая версия" if update_info['tag'] != current_build_tag else "локальный файл отсутствует"
        app_state.set_status(f"Загрузка ({reason}): {update_info['tag']}...")
        if local_mrpack_path and os.path.exists(local_mrpack_path):
            try:
                os.remove(local_mrpack_path)
                logger.info(f"Удален старый файл модпака: {local_mrpack_path}")
            except OSError as e:
                logging.warning(f"Не удалось удалить старый модпак {local_mrpack_path}: {e}")
        
        new_pack_path = download_file(
            url=update_info['url'], 
            destination_folder=game_dir, 
            filename=update_info['filename'], 
            expected_hash=update_info.get('sha512'),
            progress_callback=app_state.set_progress
        )
        if not new_pack_path:
            raise Exception(f"Не удалось скачать модпак {update_info['filename']}.")
        
        config['current_build_tag'] = update_info['tag']
        config['current_mrpack_filename'] = update_info['filename']
        save_config(config)
        update_type = "full" if not local_version else "incremental"
    elif update_type == "none":
        app_state.set_status("Сборка актуальна, пропускаем обновление...")
        logger.info("Обновление сборки не требуется")
        return
        
    update_type_ru = 'Инкрементальная' if update_type == 'incremental' else 'Полная'
    app_state.set_status(f"{update_type_ru} установка / проверка модов...")
    app_state.set_progress(0)
    final_mrpack_path = _get_mrpack_path(config)
    if not final_mrpack_path: raise Exception("Файл модпака (.mrpack) не найден. Подключитесь к интернету для его скачивания.")
    
    install_modpack(final_mrpack_path, game_dir, progress_callback=app_state.set_progress, update_type=update_type, config=config)
    update_version_info_in_state(config)
    
    versions = _get_versions_from_mrpack(load_config())
    if not versions: raise Exception("Не удалось прочитать версии из .mrpack файла после установки.")
    
    runner.set_versions(versions['minecraft'], versions.get('fabric'))
    app_state.set_status("Подготовка окружения Minecraft...")
    runner.install_minecraft_dependencies()

def _threaded_verify(config):
    runner = None
    try:
        runner = MinecraftRunner(config=config, status_callback=app_state.set_status)
        if not runner.prepare_environment(): raise RuntimeError(runner.get_last_error())
        _threaded_generic_install(config, runner)
        _save_installation_version(config)
        app_state.set_status("Проверка успешно завершена!")
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Ошибка в потоке проверки: {error_msg}", exc_info=True)
        if not app_state.get_all()['status_text'].startswith("Ошибка:"): app_state.set_status(f"Ошибка: {error_msg}")
    finally:
        if app_state.is_processing:
            current_status = app_state.get_all()['status_text']
            final_status = current_status if current_status.startswith("Ошибка:") else "Проверка завершена."
            app_state.finish_processing(final_status)

def _threaded_launch(account_info, config):
    launch_runner = None
    try:
        versions = _get_versions_from_mrpack(config)
        minecraft_version = versions['minecraft'] if versions else None
        fabric_version = versions.get('fabric') if versions else None
        launch_runner = MinecraftRunner(config=config, account_info=account_info, version=minecraft_version, fabric_version=fabric_version, status_callback=app_state.set_status)
        if not launch_runner.prepare_environment(): raise RuntimeError(launch_runner.get_last_error())
        # --- Теперь _is_installation_valid учитывает тег релиза ---
        if _is_installation_valid(config):
            app_state.set_status("Установка актуальна, пропускаем проверку...")
            logger.info("Установка валидна, пропускаем полную проверку")
        else:
            app_state.set_status("Требуется обновление файлов...")
            _threaded_generic_install(config, launch_runner)
            _save_installation_version(config)
        
        app_state.set_status("Запуск Minecraft...")
        process = launch_runner.run_only()
        if process:
            app_state.finish_processing("Игра запущена! Лаунчер можно закрыть.")

            # --- Start integrity checker ---
            # (Блок запуска IntegrityChecker полностью удалён)
            # --- End integrity checker ---

            process.wait()
            app_state.set_status("Игра закрыта.")
        else:
            raise Exception(launch_runner.get_last_error() or "Не удалось запустить процесс Minecraft.")
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Ошибка в потоке запуска: {error_msg}", exc_info=True)
        if not app_state.get_all()['status_text'].startswith("Ошибка:"): app_state.set_status(f"Ошибка: {error_msg}")
    finally:
        if app_state.is_processing:
            current_status = app_state.get_all()['status_text']
            final_status = current_status if current_status.startswith("Ошибка:") else "Процесс запуска завершен."
            app_state.finish_processing(final_status)

# --- Mod Management ---
@app.route('/api/mods', methods=['GET'])
def get_mods():
    config = load_config()
    mod_manager = ModManager(config=config)
    mods = mod_manager.get_all_mods()
    return jsonify(sorted(mods, key=lambda m: m.get('name', '')))

@app.route('/api/mods/state', methods=['POST'])
def set_mod_state_json():
    data = request.get_json(force=True)
    filename = data.get('filename')
    enable = data.get('enable')
    logger.info(f"[API] Запрос на смену состояния мода: filename='{filename}', enable={enable}")
    if not filename or enable is None:
        logger.error(f"[API] Некорректные параметры запроса: filename={filename}, enable={enable}")
        return jsonify({"error": "Missing filename or enable parameter"}), 400
    config = load_config()
    mod_manager = ModManager(config=config)
    result = mod_manager.set_mod_state(filename, enable)
    if result:
        logger.info(f"[API] Состояние мода '{filename}' успешно изменено (enable={enable})")
        return jsonify({"message": f"Mod {filename} state changed.", "success": True})
    else:
        logger.error(f"[API] Не удалось изменить состояние мода '{filename}' (enable={enable}). См. подробности выше.")
        return jsonify({"error": f"Mod {filename} not found or state change failed.", "success": False}), 404

@app.before_request
def log_request_info():
    pass

def run(debug_mode=False):
    """Starts the Flask server."""
    # Ensure data directories exist from the start, before logging
    try:
        os.makedirs(os.path.join(get_data_dir(), 'logs'), exist_ok=True)
        os.makedirs(os.path.join(get_data_dir(), 'renders'), exist_ok=True)
    except Exception as e:
        print(f"CRITICAL: Could not create data directories in {get_data_dir()}. Error: {e}")
    
    setup_logging(is_debug_mode=debug_mode)
    logger.info("Starting KRISTORY launcher backend API server...")

    config = load_config()
    game_dir = config.get('game_settings', {}).get('game_directory')
    if game_dir:
        ensure_directories_exist(config)

    app.run(host='127.0.0.1', port=5000, debug=debug_mode, use_reloader=False)
    logger.info("Backend server has stopped.")

    