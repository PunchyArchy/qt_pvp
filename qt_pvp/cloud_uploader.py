import os
from datetime import datetime
from webdav3.client import Client
import posixpath

# Настройки подключения к WebDAV серверу
options = {
    'webdav_hostname': os.environ.get("webdav_hostname"),
    'webdav_login': os.environ.get("webdav_login"),
    'webdav_password': os.environ.get("webdav_password")
}

#options = {
#    'webdav_hostname': "https://webdav.cloud.mail.ru/",
#    'webdav_login': "qodex.tech@mail.ru",
#    'webdav_password': "8byRneRA97fy4gknwRQG"
#}

client = Client(options)


def parse_filename(filename):
    """
    Парсинг названия файла для извлечения имени регистратора и даты.
    Предполагается, что имя файла имеет следующий формат:
    "регистр_имя_YYYY-MM-DD_HH_MM_SS.mp4"
    """
    # Разбиваем строку на части
    parts = filename.split(' ')
    main_part = parts[0]
    main_parts = main_part.split("_")
    reg_id = main_parts[0]
    date_str = main_parts[1]
    return reg_id, date_str


def create_folder_if_not_exists(client, folder_path):
    """
    Проверяем существование папки и создаем её, если она отсутствует.
    """
    if not client.check(folder_path):
        print(f"Папка {folder_path} не существует. Создаю...")
        client.mkdir(folder_path)


def upload_file_to_cloud(client, local_file_path, remote_folder_path):
    """
    Загрузка файла на WebDAV сервер в указанную папку.
    """
    try:
        remote_path = posixpath.join(remote_folder_path,
                                     os.path.basename(local_file_path))
        client.upload_sync(remote_path=remote_path,
                           local_path=local_file_path)
        print(f"Файл {local_file_path} успешно загружен.")
        return True
    except Exception as e:
        print(f"Ошибка загрузки файла {local_file_path}: {e}")


def delete_local_file(local_file_path):
    """
    Удаление локального файла после успешной загрузки.
    """
    try:
        os.remove(local_file_path)
        print(f"Локальный файл {local_file_path} удалён.")
    except OSError as e:
        print(f"Не удалось удалить локальный файл {local_file_path}: {e}")


def main(local_directory, dest_directory):
    for file in os.listdir(local_directory):
        if not file.endswith('.mp4'):
            continue  # Пропускаем файлы, которые не являются видеофайлами
        full_file_path = os.path.join(local_directory, file)
        # Парсим имя файла
        registr_name, date_str = parse_filename(file)
        # Формируем пути на удаленном сервере
        registr_folder = posixpath.join(dest_directory, registr_name)
        date_folder = f'{date_str}'
        remote_folder_path = posixpath.join(registr_folder, date_folder)
        # Проверяем и создаем папки, если их нет
        create_folder_if_not_exists(client, registr_folder)
        create_folder_if_not_exists(client, remote_folder_path)
        # Загружаем файл на сервер
        success = upload_file_to_cloud(
            client, full_file_path, remote_folder_path)
        if success:
            # Удаляем локальную копию файла
            delete_local_file(full_file_path)


def upload_file(file_path, dest_directory):
    registr_name, date_str = parse_filename(os.path.basename(file_path))
    # Формируем пути на удаленном сервере
    registr_folder = posixpath.join(dest_directory, registr_name)
    date_folder = f'{date_str}'
    remote_folder_path = posixpath.join(registr_folder, date_folder)
    # Проверяем и создаем папки, если их нет
    create_folder_if_not_exists(client, registr_folder)
    create_folder_if_not_exists(client, remote_folder_path)
    # Загружаем файл на сервер
    success = upload_file_to_cloud(
        client, file_path, remote_folder_path)
    return success

