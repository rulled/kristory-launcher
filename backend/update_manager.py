
import requests
import logging
import os
import zipfile
import json
import shutil
import hashlib
from .paths import get_game_dir

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/rulled/kristory/releases/latest"

def get_local_version(config):
    """Получает локальную версию сборки из папки ИГРЫ."""
    game_dir = get_game_dir(config)
    if not game_dir: return None
    version_file = os.path.join(game_dir, ".modpack_version")
    if os.path.exists(version_file):
        try:
            with open(version_file, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Ошибка чтения локальной версии: {e}")
    return None

def save_local_version(config, version):
    """Сохраняет локальную версию сборки в папку ИГРЫ."""
    game_dir = get_game_dir(config)
    if not game_dir: return
    version_file = os.path.join(game_dir, ".modpack_version")
    try:
        with open(version_file, 'w') as f:
            f.write(version)
        logger.info(f"Сохранена версия сборки: {version}")
    except Exception as e:
        logger.error(f"Ошибка сохранения версии: {e}")

def check_incremental_update(local_version, remote_version):
    """Проверяет, нужно ли полное обновление или достаточно инкрементального"""
    if not local_version:
        return "full"  # Первая установка
    
    if local_version != remote_version:
        logger.info(f"Обнаружено обновление: {local_version} -> {remote_version}")
        return "incremental"  # Инкрементальное обновление
    
    return "none"  # Обновление не нужно

def check_github_for_updates():
    """
    Проверяет последний релиз на GitHub и возвращает информацию о нем.
    Возвращает словарь {'tag': 'v1.0', 'url': '...', 'filename': '...'} или None в случае ошибки.
    """
    logger.info(f"Проверка обновлений по адресу: {GITHUB_API_URL}")
    try:
        response = requests.get(GITHUB_API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        tag_name = data.get('tag_name')
        assets = data.get('assets', [])
        
        if not tag_name or not assets:
            logger.warning("В последнем релизе отсутствуют тег или файлы (assets).")
            return None
            
        mrpack_asset = next((asset for asset in assets if asset.get('name', '').endswith('.mrpack')), None)
        if not mrpack_asset:
            logger.warning("В последнем релизе не найден .mrpack файл.")
            return None
        
        # Пытаемся найти хеш-файл для нашего mrpack
        hash_asset_name = mrpack_asset.get('name') + '.sha512'
        hash_asset = next((asset for asset in assets if asset.get('name') == hash_asset_name), None)
        
        sha512_hash = None
        if hash_asset:
            try:
                hash_url = hash_asset.get('browser_download_url')
                hash_response = requests.get(hash_url, timeout=10)
                hash_response.raise_for_status()
                sha512_hash = hash_response.text.split()[0].strip()
                logger.info(f"Найден SHA512 хеш для {mrpack_asset.get('name')}: {sha512_hash}")
            except Exception as e:
                logger.warning(f"Не удалось скачать или прочитать файл хеша {hash_asset_name}: {e}")

        return {
            'tag': tag_name,
            'url': mrpack_asset.get('browser_download_url'),
            'filename': mrpack_asset.get('name'),
            'sha512': sha512_hash
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к GitHub API: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при проверке обновлений: {e}", exc_info=True)
        return None

def download_file(url, destination_folder, filename, expected_hash=None, progress_callback=None):
    """
    Скачивает файл по URL в указанную папку с проверкой хеша.
    Скачивание происходит во временный файл, который переименовывается после успешной загрузки.
    """
    logger.info(f"Скачивание файла {filename} из {url}")
    os.makedirs(destination_folder, exist_ok=True) # Ensure destination exists
    final_filepath = os.path.join(destination_folder, filename)
    temp_filepath = final_filepath + ".tmp"
    
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(temp_filepath, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress = (downloaded / total_size)
                    progress_callback(progress)
        
        logger.info(f"Файл {filename} скачан, проверка целостности...")
        
        if expected_hash:
            local_hash = _get_sha512(temp_filepath)
            if local_hash.lower() != expected_hash.lower():
                raise ValueError(f"Хеш-сумма файла {filename} не совпадает. Ожидался: {expected_hash}, получен: {local_hash}")
            logger.info("Хеш-сумма файла подтверждена.")

        shutil.move(temp_filepath, final_filepath)
        logger.info(f"Файл {filename} успешно сохранен в {destination_folder}")
        return final_filepath

    except (requests.exceptions.RequestException, ValueError, IOError) as e:
        logger.error(f"Ошибка при скачивании файла {filename}: {e}", exc_info=True)
        # Удаляем временный файл в случае ошибки
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass
        return None

def unpack_mrpack(pack_path, temp_dir):
    """
    Распаковывает .mrpack файл во временную директорию.
    """
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    logging.info(f"Unpacking {pack_path} to {temp_dir}...")
    with zipfile.ZipFile(pack_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    index_path = os.path.join(temp_dir, 'modrinth.index.json')
    
    if not os.path.exists(index_path):
        raise FileNotFoundError("modrinth.index.json not found in the mrpack file.")
        
    logging.info("Unpacking complete.")
    return index_path

def parse_index(index_path):
    """Парсит файл modrinth.index.json и возвращает данные."""
    logging.info(f"Parsing {index_path}...")
    with open(index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    logging.info(f"Successfully parsed {index_path}.")
    return data

def _get_sha512(filename):
    """Вычисляет SHA512 хеш файла."""
    sha512 = hashlib.sha512()
    try:
        with open(filename, 'rb') as f:
            while True:
                data = f.read(65536)  # 64kb
                if not data:
                    break
                sha512.update(data)
    except IOError as e:
        logger.error(f"Не удалось прочитать файл для хеширования {filename}: {e}")
        return ""
    return sha512.hexdigest()

def sync_mods_folder(config, files_from_mrpack):
    """
    Синхронизирует папку mods. Удаляет моды, которых нет в новом списке,
    но не трогает моды из папки mods_disabled.
    """
    from .paths import get_mods_dir
    mods_dir = get_mods_dir(config)
    if not mods_dir or not os.path.exists(mods_dir):
        return

    expected_mod_filenames = {os.path.basename(file_info['path']) for file_info in files_from_mrpack if file_info['path'].startswith('mods/')}
    
    logger.info(f"Синхронизация папки mods. Ожидается {len(expected_mod_filenames)} модов.")

    try:
        actual_mod_files = {f for f in os.listdir(mods_dir) if os.path.isfile(os.path.join(mods_dir, f))}
    except FileNotFoundError:
        return # Папки нет, нечего синхронизировать

    files_to_delete = actual_mod_files - expected_mod_filenames
    
    if not files_to_delete:
        logger.info("Удаление старых модов не требуется. Все файлы актуальны.")
        return

    logger.warning(f"Найдено {len(files_to_delete)} устаревших или удаленных модов для удаления.")
    for filename in files_to_delete:
        try:
            filepath = os.path.join(mods_dir, filename)
            os.remove(filepath)
            logger.info(f"Удален устаревший мод: {filename}")
        except OSError as e:
            logger.error(f"Не удалось удалить устаревший мод {filename}: {e}")


def download_files(files, install_dir, progress_callback=None):
    """Скачивает файлы из списка, пропуская те, что уже существуют и совпадают по хешу."""
    total_files = len(files)
    logger.info(f"Найдено {total_files} файлов для проверки и скачивания.")
    
    if total_files == 0:
        if progress_callback: progress_callback(1.0)
        return

    for i, file_info in enumerate(files):
        path = os.path.join(install_dir, *file_info['path'].split('/'))
        expected_hash = file_info.get('hashes', {}).get('sha512')

        # Progress update before check
        if progress_callback: progress_callback(i / total_files)

        if os.path.exists(path) and expected_hash:
            try:
                local_hash = _get_sha512(path)
                if local_hash.lower() == expected_hash.lower():
                    logger.info(f"Файл {os.path.basename(path)} уже существует и хеш совпадает. Пропускаем.")
                    continue
            except Exception as e:
                logger.warning(f"Ошибка проверки хеша для {path}: {e}. Файл будет скачан заново.")
        
        logger.info(f"Скачивание: {os.path.basename(path)}")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Определяем URL для скачивания: сначала поле 'url', затем первый элемент из 'downloads'
        download_url = file_info.get('url')
        if not download_url:
            downloads_list = file_info.get('downloads')
            if downloads_list and isinstance(downloads_list, list):
                download_url = downloads_list[0]

        if not download_url:
            logger.error(f"Не удалось определить URL для {os.path.basename(path)}. Пропуск.")
            continue

        try:
            download_file(download_url, os.path.dirname(path), os.path.basename(path), expected_hash=expected_hash)
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке {os.path.basename(path)}: {e}")
        
    if progress_callback: progress_callback(1.0)
    logger.info("Проверка и скачивание завершены.")


def install_modpack(pack_path, install_dir, progress_callback=None, update_type="full", config=None):
    """
    Основная функция для установки модпака из .mrpack файла.
    update_type: "full" - полная установка, "incremental" - только измененные файлы
    """
    temp_dir = os.path.join(install_dir, "temp_mrpack_installation")
    logging.info(f"Starting {'incremental' if update_type == 'incremental' else 'full'} installation of {pack_path} to {install_dir}")
    logging.info(f"Using temporary directory: {temp_dir}")

    try:
        index_path = unpack_mrpack(pack_path, temp_dir)
        modpack_data = parse_index(index_path)
        files_to_download = modpack_data.get('files', [])
        dependencies = modpack_data.get('dependencies', {})

        # Синхронизируем моды на основе mrpack, если это полное обновление
        sync_mods_folder(config, files_from_mrpack=files_to_download)
        
        download_files(files_to_download, install_dir, progress_callback=progress_callback)
        
        logging.info("Copying overrides...")
        for override_folder in ['overrides', 'client-overrides']:
            src_dir = os.path.join(temp_dir, override_folder)
            if os.path.isdir(src_dir):
                shutil.copytree(src_dir, install_dir, dirs_exist_ok=True)
        logging.info("Overrides copied.")
        
        # Сохраняем версию после успешной установки
        # Извлекаем версию из имени файла или используем текущую дату
        version = os.path.basename(pack_path).replace('.mrpack', '')
        save_local_version(config, version)
        

    except Exception as e:
        logging.error(f"An error occurred during installation: {e}", exc_info=True)
        # Re-raise the exception to be caught by the calling thread
        raise e
    finally:
        logging.info(f"Cleaning up temporary directory: {temp_dir}")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except OSError as e:
                logging.error(f"Could not clean up temp directory {temp_dir}: {e}")
        logging.info("Cleanup complete.")

    logging.info("Installation finished.")
    return dependencies


    
