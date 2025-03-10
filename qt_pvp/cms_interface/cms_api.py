from qt_pvp.cms_interface import functions
from qt_pvp.logger import logger
from qt_pvp import settings
import datetime
import requests
import aiohttp
import asyncio
import time


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
            time.sleep(2)
    # while result != 11:
    #    if not return_path:
    #        break
    #    response_json = response.json()
    #    return response_json["oldTaskAll"]["dph"]


def get_interest_download_path(jsession, interest, remove_urls=True):
    file_paths = []
    if "download_tasks" in interest.keys():
        for task_url in interest["download_tasks"]:
            file_path = wait_and_get_dwn_url(
                jsession=jsession,
                download_task_url=task_url)
            file_paths.append(file_path)
        if remove_urls:
            interest.pop("download_tasks")
    logger.debug(f"Found file paths {file_paths} "
                 f"for interest {interest['name']}")
    interest["file_paths"] = file_paths
    return interest


async def download_interest_videos(jsession, interests, chanel_id,
                                   split=False):
    for interest in interests:
        # if interests.index(interest) == 0:
        #    continue
        logger.debug(f"Working with interest - {interest}")
        start_time_datetime = datetime.datetime.strptime(
            interest["start_time"], "%Y-%m-%d %H:%M:%S")
        # end_time_datetime = datetime.datetime.strptime(
        #    interest["end_time"], "%Y-%m-%d %H:%M:%S")F
        start_time_seconds = interest["beg_sec"]
        end_time_seconds = interest["end_sec"]
        if split:
            time_splits = functions.split_time(
                start_time=start_time_seconds,
                end_time=end_time_seconds,
                split=split)
        else:
            time_splits = [(start_time_seconds, end_time_seconds)]
        logger.debug(f"Got time splits: {time_splits}. Split - {split}")
        download_tasks = []
        for time_split in time_splits:
            logger.debug(f"Working with time split - {time_split}")
            response = get_video(
                jsession=jsession,
                device_id=interest["device_id"],
                chanel_id=chanel_id,
                start_time_seconds=time_split[0],
                end_time_seconds=time_split[1],
                year=start_time_datetime.year,
                month=start_time_datetime.month,
                day=start_time_datetime.day
            )
            response_json = response.json()
            logger.debug(f"Result: {response_json}, {response.status_code}")
            if "files" not in response_json.keys():
                continue
            files = response_json["files"]
            for file in files:
                download_task_url = file["DownTaskUrl"]
                # await execute_download_task(jsession=jsession,
                #                      download_task_url=download_task_url)
                await wait_and_get_dwn_url(jsession=jsession,
                                           download_task_url=download_task_url)
                download_tasks.append(download_task_url)
        interest["download_tasks"] = download_tasks

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
