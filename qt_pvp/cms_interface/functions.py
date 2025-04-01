from qt_pvp.logger import logger
from qt_pvp import settings
import datetime
import requests
import functools
import asyncio


def int_to_32bit_binary(number):
    # Преобразуем число в 32-битное представление, учитывая знак
    binary_str = format(number & 0xFFFFFFFF, '032b')
    bits = [int(bit) for bit in binary_str]
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
        "io4": bits_list[23],
        "io5": bits_list[24],
    }


def get_interest_from_track(track, start_time: str, end_time: str,
                            photo_before_timestamp: str = None,
                            photo_after_timestamp: str = None):
    start_time_datetime = datetime.datetime.strptime(start_time,
                                                     "%Y-%m-%d %H:%M:%S")
    end_time_datetime = datetime.datetime.strptime(end_time,
                                                   "%Y-%m-%d %H:%M:%S")
    photo_before_datetime = datetime.datetime.strptime(photo_before_timestamp,
                                                       "%Y-%m-%d %H:%M:%S")
    photo_after_datetime = datetime.datetime.strptime(photo_after_timestamp,
                                                      "%Y-%m-%d %H:%M:%S")

    return {
        "name": f"{track['vid']}_"
                f"{start_time_datetime.year}."
                f"{start_time_datetime.month}."
                f"{start_time_datetime.day} "
                f"{start_time_datetime.hour}."
                f"{start_time_datetime.minute}."
                f"{start_time_datetime.second}-"
                f"{end_time_datetime.hour}."
                f"{end_time_datetime.minute}."
                f"{end_time_datetime.second}",
        "beg_sec": seconds_since_midnight(start_time_datetime),
        "end_sec": seconds_since_midnight(end_time_datetime),
        "year": start_time_datetime.year,
        "month": start_time_datetime.month,
        "day": start_time_datetime.day,
        "start_time": start_time,
        "end_time": end_time,
        "device_id": track["did"],
        "car_number": track["vid"],
        "photo_before_timestamp": photo_before_timestamp,
        "photo_after_timestamp": photo_after_timestamp,
        "photo_before_sec": seconds_since_midnight(photo_before_datetime),
        "photo_after_sec": seconds_since_midnight(photo_after_datetime),
    }


def find_stops(tracks):
    stop_intervals = []
    start_time = None
    gt_time = None
    logger.info("Getting interests by stops")

    for track in tracks:
        speed = track.get("sp", 0)
        gt_time = track.get("gt")

        if gt_time:
            current_time = gt_time
        else:
            continue

        if speed <= 50:
            if start_time is None:
                start_time = current_time
        else:
            if start_time is not None:
                stop_intervals.append(
                    get_interest_from_track(track, start_time, current_time))
                start_time = None  # Сбрасываем start_time после добавления

    if start_time is not None and gt_time:
        stop_intervals.append(
            get_interest_from_track(tracks[-1], start_time, gt_time))

    # Возвращаем список без первого и последнего элемента
    return stop_intervals[1:-1] if len(stop_intervals) > 2 else []


def find_by_lifting_switches(tracks, sec_before=30, sec_after=30):
    loading_intervals = []
    i = 0
    while i < len(tracks):
        track = tracks[i]
        s1 = track.get("s1")
        timestamp = track.get("gt")

        try:
            s1_int = int(s1)
        except (ValueError, TypeError):
            i += 1
            continue

        bits = list(bin(s1_int & 0xFFFFFFFF)[2:].zfill(32))
        bits.reverse()

        # Если найдено срабатывание концевика
        if bits[22] == '1' or bits[23] == '1':
            switch_events = []
            current_dt = datetime.datetime.strptime(timestamp,
                                                    "%Y-%m-%d %H:%M:%S")
            time_30_before_dt = current_dt - datetime.timedelta(
                seconds=sec_before)

            # Ищем момент остановки до первого срабатывания
            time_before = None
            j = i
            while j >= 0:
                spd = tracks[j].get("sp") or 0
                if spd <= 10:
                    time_before = tracks[j].get("gt")
                else:
                    break
                j -= 1

            lifting_end_idx = i
            last_switch_index = i

            # Добавляем первое срабатывание
            if bits[22] == '1':
                switch_events.append({"datetime": timestamp, "switch": 22})
            if bits[23] == '1':
                switch_events.append({"datetime": timestamp, "switch": 23})

            # Продолжаем искать последующие срабатывания, пока машина стоит
            while lifting_end_idx + 1 < len(tracks):
                next_track = tracks[lifting_end_idx + 1]
                next_s1 = next_track.get("s1")
                next_spd = next_track.get("sp") or 0
                try:
                    next_s1_int = int(next_s1)
                except (ValueError, TypeError):
                    break

                next_bits = list(bin(next_s1_int & 0xFFFFFFFF)[2:].zfill(32))
                next_bits.reverse()

                if next_bits[22] == '1' or next_bits[23] == '1':
                    lifting_end_idx += 1
                    sw_time = next_track.get("gt")
                    if next_bits[22] == '1':
                        switch_events.append(
                            {"datetime": sw_time, "switch": 22})
                    if next_bits[23] == '1':
                        switch_events.append(
                            {"datetime": sw_time, "switch": 23})
                    last_switch_index = lifting_end_idx
                elif next_spd <= 10:
                    lifting_end_idx += 1
                else:
                    break

            # Ищем момент движения после последнего срабатывания
            time_after = None
            k = last_switch_index + 1
            while k < len(tracks):
                spd = tracks[k].get("sp") or 0
                if spd > 10:
                    if k > 0:
                        time_after = tracks[k - 1].get("gt")
                    break
                k += 1

            last_alarm_dt = datetime.datetime.strptime(
                tracks[last_switch_index].get("gt"), "%Y-%m-%d %H:%M:%S")
            time_30_after_dt = last_alarm_dt + datetime.timedelta(
                seconds=sec_after)
            time_30_after = time_30_after_dt.strftime("%Y-%m-%d %H:%M:%S")

            if time_before and time_after:
                interval = get_interest_from_track(
                    tracks[-1],
                    start_time=time_30_before_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=time_30_after,
                    photo_before_timestamp=time_before,
                    photo_after_timestamp=time_after
                )
                # interval["switch_events"] = switch_events
                load_report = {"geo": track["ps"],
                               "switches_amount": len(switch_events),
                               "switch_events": switch_events}

                interval["report"] = load_report
                loading_intervals.append(interval)

            i = lifting_end_idx + 1
        else:
            i += 1

    return loading_intervals


def find_by_lifting_switches_depr(tracks, sec_before=30, sec_after=30):
    loading_intervals = []
    start_time = None
    last_alarm_time = None
    logger.info(
        "Анализ треков на остановку по концевикам подъемного механизма")
    for track in tracks:
        speed = track.get("sp", 0)  # Скорость машины
        s1_analyze = analyze_s1(track["s1"])
        switch = s1_analyze["io3"] or s1_analyze["io4"]
        current_time = datetime.datetime.strptime(track.get("gt"),
                                                  "%Y-%m-%d %H:%M:%S")  # Время события

        # Если сработал концевик (alarm 3 или alarm 4)
        if switch:
            if start_time is None:
                # Начало - 30 секунд до первой сработки
                start_time = current_time - datetime.timedelta(
                    seconds=sec_before)

            # Запоминаем последнюю сработку концевика
            last_alarm_time = current_time

        # Если машина поехала (speed > 0) и ранее была фиксация загрузки
        if speed > 0 and start_time:
            # Завершаем текущий интервал загрузки
            end_time = last_alarm_time + datetime.timedelta(seconds=sec_after)
            loading_intervals.append(
                get_interest_from_track(
                    track,
                    start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time.strftime("%Y-%m-%d %H:%M:%S"))
            )

            # Сбрасываем переменные для нового интервала
            start_time = None
            last_alarm_time = None

    # Добавляем последний интервал, если машина так и не поехала
    if start_time and last_alarm_time:
        end_time = last_alarm_time + datetime.timedelta(seconds=30)
        loading_intervals.append(
            get_interest_from_track(
                tracks[-1],
                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S"))
        )

    return loading_intervals


def analyze_tracks_get_interests(tracks, by_stops=False,
                                 continuous=False,
                                 by_lifting_limit_switch=False):
    # was_stop = None
    interests = []
    # print(tracks)
    if by_stops:
        interests = find_stops(tracks)
        return interests[1:-1] if len(interests) > 2 else []
    elif by_lifting_limit_switch:
        interests = find_by_lifting_switches(tracks)
        return interests
    elif continuous:
        interests = get_interest_from_track(
            tracks[-1], tracks[0]["gt"], tracks[-1]["gt"])
    logger.debug(f"Get interests: {interests}")
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


def cms_data_get_decorator_async(max_retries=3, delay=1):
    """
    Декоратор для повторного выполнения запросов к CMS серверу в случае ошибок.
    :param max_retries: Максимальное количество попыток.
    :param delay: Задержка между попытками (в секундах).
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    # Выполняем асинхронную функцию
                    result = await func(*args, **kwargs)
                    # Проверяем ответ (предполагаем, что ответ — это JSON)
                    if isinstance(result, dict) and result.get(
                            "result") == 24:
                        raise ValueError("Invalid response from CMS server")

                    # Если ответ корректен, возвращаем его
                    return result
                except (ValueError, Exception) as e:
                    retries += 1
                    logger.warning(
                        f"Attempt {retries} failed: {e}. Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)

            # Если все попытки исчерпаны, вызываем исключение
            raise Exception(f"Failed after {max_retries} retries")

        return wrapper

    return decorator


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

