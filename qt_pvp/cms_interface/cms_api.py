from qt_pvp.cms_interface import functions
from qt_pvp.logger import logger
from qt_pvp import settings
import datetime
import requests
import aiohttp
import asyncio
import uuid
import time
import cv2
import os


@functions.cms_data_get_decorator()
def get_online_devices(jsession, device_id=None):
    return requests.get(
        f"{settings.cms_host}/StandardApiAction_getDeviceOlStatus.action?",
        params={"jsession": jsession,
                "status": 1,
                "devIdno": device_id})


@functions.cms_data_get_decorator()
def login():
    data = requests.get(
        f"{settings.cms_host}/StandardApiAction_login.action?",
        params={"account": settings.cms_login,
                "password": settings.cms_password})
    return data


@functions.cms_data_get_decorator()
def get_video(jsession, device_id: str, start_time_seconds: int,
              end_time_seconds: int, year: int, month: int, day: int,
              chanel_id: int = 0, fileattr: int = 2):
    params = {"DevIDNO": device_id,
              "LOC": 1,
              "CHN": chanel_id,
              "YEAR": year,
              "MON": month,
              "DAY": day,
              "RECTYPE": -1,
              "FILEATTR": fileattr,
              "BEG": start_time_seconds,
              "END": end_time_seconds,
              "ARM1": 0,
              "ARM2": 0,
              "RES": 0,  # RES 0
              "STREAM": -1,  # STREAM -1
              "STORE": 0,
              "jsession": jsession,
              "DownType": 2}
    url = f"{settings.cms_host}/StandardApiAction_getVideoFileInfo.action?"
    logger.debug(f"Getting request {url}. \nParams: {params}")
    return requests.get(
        url,
        params=params,
        timeout=4)


async def fetch_photo_url(data_list, chn_values):
    """
    Функция для получения пути к фото (dph) по заданным значениям chn.
    Работает только с самыми последними (свежими) записями для каждого chn.

    :param data_list: Список словарей с данными (уже отсортированный, свежие записи идут последними).
    :param chn_values: Список значений chn, которые нужно обработать.
    :return: Словарь с результатами, где ключ — chn, значение — путь к фото (dph).
    """
    # Собираем последние записи для каждого chn
    latest_items = {}
    for item in data_list:
        chn = item.get('chn')
        if chn in chn_values:
            # Просто перезаписываем значение для каждого chn
            latest_items[chn] = item

    results = {}
    async with aiohttp.ClientSession() as session:
        for chn, item in latest_items.items():
            down_task_url = item.get('DownTaskUrl')
            # Отправляем GET-запрос и ждем ответа
            while True:
                async with session.get(down_task_url) as response:
                    data = await response.json()
                    # Проверяем, появилось ли значение dph
                    if data.get("oldTaskReal", {}).get("dph") is not None:
                        results[chn] = data["oldTaskReal"]["dph"]
                        break
                    # Если dph еще не появился, ждем некоторое время
                    await asyncio.sleep(1)  # Интервал проверки — 1 секунда

    return results


def get_alarms(jsession, reg_id, begin_time, end_time):
    url = f"{settings.cms_host}/StandardApiAction_queryAlarmDetail.action?"
    print(url)
    params = {"jsession": jsession,
              "devIdno": reg_id,
              "begintime": begin_time,
              # "begintime": to_timestamp(begin_time),
              "endtime": end_time,
              # "endtime": to_timestamp(end_time),
              "armType": "19,20,69,70",
              }
    return requests.get(
        url,
        params=params
    )


@functions.cms_data_get_decorator()
def get_gps(jsession):
    response = requests.get(
        f"{settings.cms_host}/StandardApiAction_getDeviceStatus.action?",
        params={"jsession": jsession})
    return response


@functions.cms_data_get_decorator()
def get_device_track(jsession: str, device_id: str, start_time: str,
                     stop_time: str, page: int = None):
    params = {"jsession": jsession,
              "devIdno": device_id,
              "begintime": start_time,
              "endtime": stop_time,
              "currentPage": page
              }
    print(params)
    response = requests.get(
        f"{settings.cms_host}/StandardApiAction_queryTrackDetail.action?",
        params=params,
        timeout=60)
    return response


def get_device_status(jsession: str, device_id: str):
    response = requests.get(
        f"{settings.cms_host}/StandardApiAction_getDeviceStatus.action?",
        params={"jsession": jsession,
                "devIdno": device_id,
                })
    return response


def get_device_track_all_pages(jsession: str, device_id: str, start_time: str,
                               stop_time: str):
    total_pages = 2
    current_page = 1
    all_tracks = []
    while current_page < total_pages:
        tracks = get_device_track(jsession, device_id, start_time, stop_time,
                                  page=current_page)
        tracks_json = tracks.json()
        total_pages = tracks_json["pagination"]["totalPages"]
        current_page = tracks_json["pagination"]["currentPage"]
        all_tracks += tracks_json["tracks"]
        if current_page >= total_pages:
            break
    # logger.debug(f"Got tracks: {all_tracks}")
    return all_tracks


@functions.cms_data_get_decorator_async()
async def execute_download_task(jsession, download_task_url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(download_task_url,
                                   params={"jsession": jsession}) as response:
                response.raise_for_status()
                return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"HTTP request failed: {e}")
        return None


async def wait_and_get_dwn_url(jsession, download_task_url):
    logger.info("Downloading...")
    while True:
        response_json = await execute_download_task(
            jsession=jsession,
            download_task_url=download_task_url)
        result = response_json["result"]
        if result == 11 and response_json["oldTaskAll"]["dph"]:
            logger.info(f"{response_json['oldTaskAll']['id']}. Download done!")
            logger.debug(
                f'Get path: {str(response_json["oldTaskAll"]["dph"])}')
            return response_json["oldTaskAll"]["dph"]
        else:
            time.sleep(1)


async def download_interest_videos(jsession, interest, chanel_id,
                                   split=False):
    logger.info(f"Загружаем видео...")
    start_time_datetime = datetime.datetime.strptime(
        interest["start_time"], "%Y-%m-%d %H:%M:%S")
    interest["file_paths"] = []
    response = get_video(
        jsession=jsession,
        device_id=interest["device_id"],
        chanel_id=chanel_id,
        start_time_seconds=interest["beg_sec"],
        end_time_seconds=interest["end_sec"],
        year=start_time_datetime.year,
        month=start_time_datetime.month,
        day=start_time_datetime.day
    )
    response_json = response.json()

    logger.debug(
        f"Get video response: {response_json}, {response.status_code}")
    if "files" not in response_json:
        logger.warning(f"Not files found on chanel_id {chanel_id}")
        return
    files = response_json["files"]
    for file in files:
        download_task_url = file["DownTaskUrl"]
        file_path = await wait_and_get_dwn_url(
            jsession=jsession,
            download_task_url=download_task_url)
        interest["file_paths"].append(file_path)
    return interest


async def get_frames(jsession, reg_id: str,
                     year: int, month: int, day: int,
                     start_sec: int, end_sec: int):
    channels = [0, 1, 2, 3, 4]
    frames = []
    for channel_id in channels:
        videos_path = await download_video(jsession=jsession, reg_id=reg_id,
                                           channel_id=channel_id, year=year,
                                           month=month, day=day,
                                           start_sec=start_sec,
                                           end_sec=end_sec)
        logger.debug(f"Chanel id {channel_id} - {videos_path}")
        if not videos_path:
            continue
        video_path = videos_path[0]
        frame_path = extract_first_frame(video_path)
        frames.append(frame_path)
    return frames


def extract_first_frame(video_path: str,
                        output_dir: str = settings.FRAMES_TEMP_FOLDER):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        logger.error(f"Не удалось открыть видео: {video_path}")
        return False

    os.makedirs(output_dir, exist_ok=True)  # убедимся, что папка есть

    filename = f"{uuid.uuid4().hex}.jpg"
    output_path = os.path.join(output_dir, filename)

    logger.debug(f"Пытаемся сохранить кадр в {output_path}")
    success, frame = cap.read()
    if success:
        cv2.imwrite(output_path, frame)
        logger.info(f"Кадр успешно сохранён в: {output_path}")
        return output_path
    else:
        logger.warning("Не удалось прочитать кадр из видео.")
        return False


async def download_video(jsession, reg_id: str, channel_id: int,
                         year: int, month: int, day: int,
                         start_sec: int, end_sec: int):
    logger.info(
        f"{reg_id}. Загружаем видео {year}.{month}.{day} "
        f"c {start_sec} до {end_sec} (секунды). "
        f"Канал {channel_id}")
    file_paths = []
    response = get_video(
        jsession=jsession,
        device_id=reg_id,
        chanel_id=channel_id,
        start_time_seconds=start_sec,
        end_time_seconds=end_sec,
        year=year,
        month=month,
        day=day
    )
    response_json = response.json()

    logger.debug(
        f"Get video response: {response_json}, {response.status_code}")
    if "files" not in response_json:
        logger.warning(f"Not files found on chanel_id {channel_id}")
        return
    files = response_json["files"]
    for file in files:
        download_task_url = file["DownTaskUrl"]
        file_path = await wait_and_get_dwn_url(
            jsession=jsession,
            download_task_url=download_task_url)
        file_paths.append(file_path)
    return file_paths
# for interest in interests:
#    get_interest_download_path(jsession, interest)


# print(log_data)
# if res["result"] == 32:
#    pass
# print(res)
# files = res["files"]
# file = files[0]
# device_id = "104040"
# print(file["DownTaskUrl"])
# print("getting gps")
# track = gps.json()["status"]
# print(gps.json())
# tracks = get_device_track_all_pages(jsession=jsession,
# device_id=device_id,
# start_time="2025-02-05 15:00:00",
# stop_time="2025-02-05 16:00:00", )

# interests = functions.analyze_tracks_get_interests(tracks)
