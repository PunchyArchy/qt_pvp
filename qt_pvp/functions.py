from _thread import allocate_lock
from qt_pvp.logger import logger
from qt_pvp import settings
import subprocess
import datetime
import requests
import zipfile
import ffmpeg
import shutil
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


def split_time_range_to_dicts(start_time, end_time, interval):
    # Преобразуем строки в объекты datetime
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
            converted_files=converted_files,
            output_abs_name=concatenated_filename)
        # Удаляем временные файлы
        # os.remove(concat_list_path)
        for file in converted_files:
            os.remove(file)
    # r#eturn {"output_path": concatenated_filename}


def concatenate_videos(converted_files, output_abs_name):
    concat_list_path = os.path.join(os.path.dirname(output_abs_name),
                                    'concat_list.txt')
    # Создаем временный файл со списком файлов для объединения
    logger.debug(
        f"Конкатенация файлов {converted_files}")
    with open(concat_list_path, 'w') as list_file:
        for file in converted_files:
            list_file.write(f"file '{file}'\n")
    # Команда для объединения через FFMPEG
    concatenate_command = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i',
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
        logger.debug("Output dir for converted files is not specified. "
                     "Input file`s dir has been choosen.")
        output_dir = os.path.dirname(input_video_path)
    filename = os.path.basename(input_video_path)
    output_video_path = os.path.join(output_dir,
                                     filename + '.' + output_format)
    # Команда для конвертации через FFMPEG
    conversion_command = ['ffmpeg', '-y', '-i', input_video_path, '-c:v',
                          'libx264', '-crf', '23', '-preset', 'medium',
                          output_video_path]
    logger.debug(
        f"Команда на конвертацию {' '.join(conversion_command)}")
    try:
        subprocess.run(conversion_command, check=True)
    except subprocess.CalledProcessError:
        logger.critical("Ошибка конвертации!")
        return None
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
    if not reg_info:
        return
    return reg_info["interests"]


def save_new_interests(reg_id, interests):
    states = get_json_states()
    if not reg_id in states["regs"]:
        create_new_reg(reg_id)
    states["regs"][reg_id]["states"] = interests
    save_new_states_to_file(states)


def clean_interests(reg_id):
    logger.debug("Cleaning interests in states.json")
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
        "chanel_id": 0,
        "last_upload_time": last_upload.strftime("%Y-%m-%d %H:%M:%S"),
        "door_limit_switch": 0,
        "lifting_limit_switch": 0
    }
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


def get_video_info(file_path):
    """
    Получает информацию о видеофайле: формат и видеокодек.
    """
    try:
        probe = ffmpeg.probe(file_path)
        print(probe)
        format_name = probe['format']['format_name']
        video_stream = next((stream for stream in probe['streams'] if
                             stream['codec_type'] == 'video'), None)
        video_codec = video_stream['codec_name'] if video_stream else None
        return format_name, video_codec
    except ffmpeg.Error as e:
        logger.error(f"Ошибка при анализе файла {file_path}: {e.stderr}")
        return None, None


def convert_to_mp4_h264(input_file, output_file):
    """
    Конвертирует видео в MP4 с кодеком H.264.
    Если входной видеофайл в формате .ifv, сначала исправляет временные метки.
    """
    try:
        input_ext = os.path.splitext(input_file)[-1].lower()

        # Если файл уже MP4 H.264, просто копируем
        if input_ext == ".mp4":
            video_codec = get_video_codec(input_file)
            if video_codec == "h264":
                logger.info(f"Файл {input_file} уже в формате MP4 H.264, копируем без изменений.")
                os.rename(input_file, output_file)
                return

        # Если IFV, исправляем временные метки перед конвертацией
        if ".ifv" in input_file:
            logger.info(f"Исправляем временные метки в {input_file}.")
            temp_fixed_file = input_file + "_fixed.ifv"
            (
                ffmpeg
                .input(input_file, fflags='+genpts')
                .output(temp_fixed_file, c='copy')
                .run(overwrite_output=True)
            )
            input_file = temp_fixed_file  # Используем исправленный файл дальше

        # Конвертация в MP4 H.264
        logger.info(f"Конвертируем {input_file} в MP4 H.264.")
        (
            ffmpeg
            .input(input_file)
            .output(output_file, vcodec="libx264", preset="slow", crf=23, acodec="aac", b_a="128k")
            .run(overwrite_output=True)
        )

        logger.info(f"Файл успешно обработан: {output_file}")

        # Удаляем временный файл, если он был создан
        if ".ifv" in input_file:
            os.remove(temp_fixed_file)

    except ffmpeg.Error as e:
        logger.error(f"Ошибка при обработке файла {input_file}: {e.stderr}")


def get_video_codec(file_path):
    """
    Определяет видеокодек файла через ffmpeg.
    """
    try:
        probe = ffmpeg.probe(file_path)
        return probe["streams"][0]["codec_name"]
    except Exception as e:
        logger.warning(f"Не удалось определить кодек для {file_path}: {e}")
        return None  # Если не удалось определить, возвращаем None


def process_video_file(file_path):
    """
    Обрабатывает видеофайл: проверяет формат и кодек, при необходимости конвертирует.
    """
    # Получаем информацию о файле
    format_name, video_codec = get_video_info(file_path)
    if not format_name or not video_codec:
        logger.error(f"Не удалось получить информацию о файле: {file_path}")
        return file_path

    logger.info(f"Файл: {file_path}")
    logger.info(f"Формат: {format_name}")
    logger.info(f"Видеокодек: {video_codec}")

    # Определяем, нужно ли конвертировать
    need_conversion = False
    if format_name != 'mp4':
        need_conversion = True
        logger.info("Файл не в формате MP4. Требуется конвертация.")
    elif video_codec != 'h264':
        need_conversion = True
        logger.info(
            "Файл в формате MP4, но кодек не H.264. Требуется конвертация.")
    else:
        logger.info(
            "Файл уже в формате MP4 с кодеком H.264. Конвертация не требуется.")

    # Конвертируем, если нужно
    if need_conversion:
        output_file = os.path.splitext(file_path)[0] + "_converted.mp4"
        convert_to_mp4_h264(file_path, output_file)
        return output_file
    return file_path
