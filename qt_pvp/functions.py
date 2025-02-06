from _thread import allocate_lock
from qt_pvp.logger import logger
from qt_pvp import settings
import subprocess
import datetime
import requests
import zipfile
import json
import uuid
import time
import os

json_states_mutex = allocate_lock()


def unzip_archives_in_directory(input_dir, output_dir):
    # Проверка существования входящей директории
    logger.debug(f'Распаковка {input_dir} в {output_dir}')
    if not os.path.exists(input_dir):
        logger.error(f'Директория {input_dir} не найдена')
        return
    # Получение списка всех файлов в input_dir
    files = os.listdir(input_dir)
    for file in files:
        logger.debug(f'Распаковка файла {file}...')
        # Проверяем, является ли файл архивом .zip
        if file.endswith('.zip'):
            zip_path = os.path.join(input_dir, file)
            # Определяем имя архива без расширения
            archive_name = os.path.splitext(file)[0]
            # Формируем путь для новой директории
            new_output_dir = os.path.join(output_dir, archive_name)
            if os.path.exists(new_output_dir):
                continue
            # Создаём новую директорию, если она не существует
            if not os.path.exists(new_output_dir):
                os.makedirs(new_output_dir)
            # Распаковка архива
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(path=new_output_dir)
                logger.debug(
                    f'Файл {file} успешно распакован в {new_output_dir}.')
    logger.info(f'Распаковка {input_dir} в {output_dir} завершена.')


def split_time_range_to_dicts(start_time_str, end_time_str, interval):
    # Преобразуем строки в объекты datetime
    start_time = datetime.datetime.strptime(start_time_str,
                                            "%Y.%m.%d %H:%M:%S")
    end_time = datetime.datetime.strptime(end_time_str,
                                          "%Y.%m.%d %H:%M:%S")
    # Проверяем, чтобы начало было раньше конца
    if start_time >= end_time:
        raise ValueError("Время начала должно быть раньше времени окончания.")
    # Создаем пустой список для хранения результатов
    result = []
    current_time = start_time
    while current_time + interval <= end_time:
        next_time = min(current_time + interval, end_time)
        result.append({
            'time_start': current_time,
            'time_end': next_time
        })
        current_time = next_time
    return result


def convert_and_concatenate_videos(input_dir, output_format='mp4'):
    # Проверка существования входящей директории
    logger.info(f"Начало обработки видео (конвертация и конкатенация)...")
    if not os.path.exists(input_dir):
        logger.error(f"Директория {input_dir} не найдена!")
    # Получение списка всех поддиректорий в input_dir
    sub_dirs = [d for d in os.listdir(input_dir) if
                os.path.isdir(os.path.join(input_dir, d))]
    logger.debug(f"Получен список поддиректорий - {sub_dirs}")
    for subdir in sub_dirs:
        logger.debug(f"Работаем с {subdir}")
        # Полный путь до поддиректории
        subdir_path = os.path.join(input_dir, subdir)
        # Получение списка всех файлов в поддиректории
        video_files = [f for f in os.listdir(subdir_path) if
                       f.endswith('.grec')]
        # Сортируем файлы по имени
        video_files.sort()
        # Преобразование каждого файла в MP4
        converted_files = []
        for video_file in video_files:
            converted_file_path = convert_video_file(video_file)
            converted_files.append(converted_file_path)
        logger.debug("Успешно сконвертированы.")
        # Объединение всех MP4 файлов в один
        concatenated_filename = os.path.join(subdir_path,
                                             f'{subdir}.{output_format}')
        concatenated_filename = concatenate_videos(
            subdir, converted_files,
            concatenated_filename)
        # Удаляем временные файлы
        # os.remove(concat_list_path)
        for file in converted_files:
            os.remove(file)
    # r#eturn {"output_path": concatenated_filename}


def concatenate_videos(temp_dir, converted_files, output_abs_name):
    concat_list_path = os.path.join(temp_dir, 'concat_list.txt')
    # Создаем временный файл со списком файлов для объединения
    with open(concat_list_path, 'w') as list_file:
        for file in converted_files:
            list_file.write(f"file '{file}'\n")
    # Команда для объединения через FFMPEG
    concatenate_command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i',
                           concat_list_path, '-c', 'copy',
                           output_abs_name]
    logger.debug(
        f"Команда на конкатенацию {' '.join(concatenate_command)}")
    subprocess.run(concatenate_command, check=True)
    logger.debug(f"Успешно объединено. "
                 f"Результат: {output_abs_name}.")
    os.remove(concat_list_path)


def convert_video_file(input_video_path: str, output_dir: str = None,
                       output_format: str = "mp4"):
    if not output_dir:
        output_dir = os.path.dirname(input_video_path)
    output_video_path = os.path.join(output_dir,
                                     os.path.splitext(input_video_path)[
                                         0] + '.' + output_format)
    # Команда для конвертации через FFMPEG
    conversion_command = ['ffmpeg', '-i', input_video_path, '-c:v',
                          'libx264', '-crf', '23', '-preset', 'medium',
                          output_video_path]
    logger.debug(
        f"Команда на конвертацию {' '.join(conversion_command)}")
    subprocess.run(conversion_command, check=True)
    return output_video_path


def get_video_zip(
        time_start: datetime.datetime,
        time_stop: datetime.datetime,
        device_id: str, channel: int):
    time_start = datetime.datetime.isoformat(time_start) + "Z"
    time_stop = datetime.datetime.isoformat(time_stop) + "Z"
    response = requests.get(settings.get_video_rout,
                            params={
                                "time_start": time_start,
                                "time_stop": time_stop,
                                "device_id": device_id,
                                "channel": channel
                            },
                            )
    if response.status_code == 200:
        file = response.content
    else:
        file = None
    logger.info(f"Получен ответ по запросу на извлечение архива с видео. "
                f"Код ответа: {response.status_code}")
    logger.debug(f"Запрос: {str(locals())}")
    return {
        "status": response.status_code,
        "content": file
    }


def save_file(file_content, destination_folder=settings.CUR_DIR,
              file_name=None):
    if not file_name:
        file_name = str(uuid.uuid4())
    if not file_name.endswith("zip"):
        file_name += ".zip"
    file_path = os.path.join(destination_folder, file_name)
    with open(file_path, 'wb') as fobj:
        fobj.write(file_content)
    return {"file_path": file_path}


def download_video(time_start: datetime.datetime,
                   time_stop: datetime.datetime,
                   device_id: str, channel: int, archive_name: str = None,
                   destination_folder=settings.CUR_DIR):
    logger.info("Получена команда на скачивание видео")
    logger.debug(str(locals()))
    video = get_video_zip(time_start=time_start, time_stop=time_stop,
                          device_id=device_id, channel=channel)
    # video is zip file containing grec files
    file_path = None
    if video["status"] == 200:
        archive_name = f"{device_id}_ch{channel} " \
                       f"{time_start.hour}-{time_start.minute}, " \
                       f"{time_stop.hour}-{time_stop.minute}"
        save_file_response = save_file(file_content=video["content"],
                                       destination_folder=destination_folder,
                                       file_name=archive_name)
        file_path = save_file_response["file_path"]
    data = {"download_status": video["status"],
            "file_path": file_path,
            "archive_name": archive_name}
    logger.info(f"Результат скачивания видео: {data}")
    return data


def get_analyze_by_alarm(date, device_id, skip_depot=False):
    eumid_response = requests.get(settings.get_alarm_analyze,
                                  params={
                                      "date": date,
                                      "device_id": device_id,
                                      "skip_depot": skip_depot
                                  }, )
    return eumid_response.json()


def get_json_states():
    json_states_mutex.acquire()
    with open(settings.states) as fobj:
        states = json.load(fobj)
    json_states_mutex.release()
    return states


def save_new_states_to_file(states):
    json_states_mutex.acquire()
    with open(settings.states, "w") as fobj:
        json.dump(states, fobj, indent=4)
    json_states_mutex.release()


def get_regs_states(**kwargs):
    return get_json_states()["regs"]


def get_interests(reg_id):
    reg_info = get_reg_info(reg_id)
    return reg_info["interests"]


def clean_interests(reg_id):
    logger.info("Cleaning interests in states.json")
    states = get_json_states()
    states["regs"][reg_id]["interests"] = []
    save_new_states_to_file(states)


def get_reg_info(reg_id):
    regs = get_regs_states()
    if reg_id not in regs.keys():
        return
    return regs[reg_id]


def create_new_reg(reg_id):
    info = get_json_states()
    if reg_id in info["regs"].keys():
        return
    last_upload = datetime.datetime.today() - datetime.timedelta(days=7)
    info["regs"][reg_id] = {
        "interests": [],
        "last_upload_time": last_upload.strftime("%Y-%m-%d %H:%M:%S")}
    save_new_states_to_file(info)


def get_reg_last_upload_time(reg_id):
    reg_info = get_reg_info(reg_id=reg_id)
    if not reg_info:
        reg_info = create_new_reg(reg_id)
    if not reg_info or "last_upload_time" not in reg_info.keys():
        return
    return reg_info["last_upload_time"]


def save_new_reg_last_upload_time(reg_id, timestamp):
    states = get_json_states()
    if not reg_id in states["regs"]:
        create_new_reg(reg_id)
    states["regs"][reg_id]["last_upload_time"] = timestamp
    save_new_states_to_file(states)


def video_remover_cycle():
    while True:
        all_videos = get_all_files(settings.INTERESTING_VIDEOS_FOLDER)
        for video_abs_name in all_videos:
            if check_if_file_old(video_abs_name):
                os.remove(video_abs_name)
        time.sleep(3600)


def get_all_files(files_dir):
    only_files = [os.path.join(files_dir, f) for f in os.listdir(files_dir)
                  if os.path.isfile(os.path.join(files_dir, f))]
    return only_files


def check_if_file_old(file_abs_path, old_time_days=60):
    ti_m = os.path.getmtime(file_abs_path)
    created_time = datetime.datetime.fromtimestamp(ti_m)
    if (datetime.datetime.now() - created_time).days >= old_time_days:
        return True
