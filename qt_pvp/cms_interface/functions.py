from qt_pvp.logger import logger
from qt_pvp import settings
import datetime
import requests


def int_to_32bit_binary(number):
    # Переводим число в двоичную строку без префикса '0b'
    binary_str = bin(number)[2:]
    # Добавляем нули слева, чтобы длина строки стала 32 символа
    padded_binary_str = binary_str.zfill(32)
    bits = [int(bit) for bit in padded_binary_str]
    bits.reverse()
    return bits


def form_add_download_task_url(reg_id, start_timestamp, end_timestamp,
                               channel_id, reg_fph=None):
    req_url = f"{settings.add_download_task}?" \
              f"did={reg_id}" \
              f"&fbtm={start_timestamp}" \
              f"&fetm={end_timestamp}" \
              f"&chn={channel_id}" \
              f"&sbtm={datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" \
              f"&dtp=2" \
              f"&ftp=2" \
              f"&vtp=0"
    return req_url


# f"&fph={reg_fph}" \


def analyze_s1(s1_int: int):
    bits_list = int_to_32bit_binary(s1_int)
    return {
        "acc_state": bits_list[1],
        "forward_state": bits_list[5],
        "static_state": bits_list[13],
        # "parked_acc_state": bits_list[19],
        "io1": bits_list[20],
        "io2": bits_list[21],
        "io3": bits_list[22],
        # "io4": bits_list[23],
        # "io5": bits_list[24],
    }


def analyze_tracks_get_interests(tracks, by_trigger=True):
    # was_stop = None
    start_time = None
    start_time_datetime = None
    interests = []
    # print(tracks)
    if not by_trigger:
        start_time_datetime = datetime.datetime.strptime(
            tracks[0]["gt"], "%Y-%m-%d %H:%M:%S")
    for track in tracks:
        track_analyze = {}
        s1 = analyze_s1(track["s1"])
        track_analyze.update(s1)
        track_analyze["speed"] = track["sp"]
        track_analyze["mlng"] = track["mlng"]
        track_analyze["mlat"] = track["mlat"]
        track_analyze["geo_pos"] = track["ps"]
        track_analyze["parking_time"] = track["pk"]
        track_analyze["mileage"] = track["lc"]
        track_analyze["gps_upload_time"] = track["gt"]
        track_analyze["device_id"] = track["vid"]
        if not by_trigger:
            end_time = track_analyze["gps_upload_time"]
            end_time_datetime = datetime.datetime.strptime(
                end_time, "%Y-%m-%d %H:%M:%S")
            if start_time_datetime and (
                    end_time_datetime - start_time_datetime).seconds >= 120:
                start_time = track_analyze["gps_upload_time"]
                start_time_datetime = datetime.datetime.strptime(
                    start_time, "%Y-%m-%d %H:%M:%S")
                interests.append({
                    "name": f"{track_analyze['device_id']}_"
                            f"{start_time_datetime.year}."
                            f"{start_time_datetime.month}."
                            f"{start_time_datetime.day} "
                            f"{start_time_datetime.hour}-"
                            f"{start_time_datetime.minute}-"
                            f"{start_time_datetime.second}_"
                            f"{end_time_datetime.hour}-"
                            f"{end_time_datetime.minute}-"
                            f"{end_time_datetime.second}",
                    "start_time": start_time,
                    "end_time": end_time,
                    "device_id": track_analyze["device_id"],
                })
            continue
        if (track_analyze["io1"] or track_analyze["io2"]) and not start_time:
            start_time = track_analyze["gps_upload_time"]
        elif track_analyze["speed"] > 60 and start_time:
            end_time = track_analyze["gps_upload_time"]
            start_time_datetime = datetime.datetime.strptime(
                start_time, "%Y-%m-%d %H:%M:%S")
            end_time_datetime = datetime.datetime.strptime(
                end_time, "%Y-%m-%d %H:%M:%S")
            if start_time_datetime < end_time_datetime:
                interests.append({
                    "name": f"{track_analyze['device_id']}_"
                            f"{start_time_datetime.year}."
                            f"{start_time_datetime.month}."
                            f"{start_time_datetime.day} "
                            f"{start_time_datetime.hour}-"
                            f"{start_time_datetime.minute}-"
                            f"{start_time_datetime.second}_"
                            f"{end_time_datetime.hour}-"
                            f"{end_time_datetime.minute}-"
                            f"{end_time_datetime.second}",
                    "start_time": start_time,
                    "end_time": end_time,
                    "device_id": track_analyze["device_id"],
                })
                start_time = None
    logger.debug(f"Get interests: {interests}")
    #raise ZeroDivisionError
    return interests


def split_time(start_time, end_time, split=30):
    # Проверка, чтобы начало было меньше конца
    if start_time >= end_time:
        return []
    intervals = []
    current_time = start_time
    while current_time + split < end_time:
        intervals.append((current_time, current_time + split))
        current_time += split
    # Добавляем последний неполный интервал, если он есть
    if current_time <= end_time:
        intervals.append((current_time, end_time))
    return intervals


def seconds_since_midnight(dt: datetime.datetime) -> int:
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = dt - midnight
    return int(delta.total_seconds())


def cms_data_get_decorator(tag='execute func'):
    # Main body
    def decorator(func):
        def wrapper(*args, **kwargs):
            while True:
                try:
                    response = func(*args, **kwargs)
                    result = response.json()["result"]
                    if result == 24:
                        continue
                    else:
                        return response
                except (requests.exceptions.ReadTimeout,
                        requests.exceptions.ConnectTimeout) as err:
                    logger.warning("Connection problem with CMS")

        return wrapper

    return decorator
