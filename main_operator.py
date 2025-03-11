from qt_pvp.cms_interface import functions as cms_api_funcs
from qt_pvp import functions as main_funcs
from qt_pvp.cms_interface import cms_api
from qt_pvp import cloud_uploader
from qt_pvp.logger import logger
from qt_pvp import settings
import asyncio
import threading
import traceback
import datetime
import shutil
import time
import os


class Main:
    def __init__(self, output_format="mp4"):
        self.jsession = cms_api.login().json()["jsession"]
        threading.Thread(target=main_funcs.video_remover_cycle).start()
        self.output_format = output_format
        self.devices_in_progress = []

    def video_ready_trigger(self, *args, **kwargs):
        logger.info("Dummy trigger activated")
        pass

    def get_devices_online(self):
        devices_online = cms_api.get_online_devices(self.jsession)
        devices_online = devices_online.json()["onlines"]
        if devices_online:
            logger.debug(f"Got devices online: {devices_online}")
        return devices_online

    async def operate_device(self, reg_id):
        if reg_id in self.devices_in_progress:
            return
        self.devices_in_progress.append(reg_id)
        try:
            await self.download_reg_videos(reg_id, by_trigger=True)
        except:
            logger.error(traceback.format_exc())
        else:
            self.devices_in_progress.remove(reg_id)

    def get_interests(self, reg_id, start_time, stop_time, by_trigger):
        interest_saved = main_funcs.get_interests(reg_id)
        if not interest_saved:
            tracks = cms_api.get_device_track_all_pages(
                jsession=self.jsession,
                device_id=reg_id,
                start_time=start_time,
                stop_time=stop_time,
            )
            if by_trigger:
                interests = cms_api_funcs.analyze_tracks_get_interests(
                    tracks, by_trigger)
                main_funcs.save_new_interests(reg_id, interests)
            else:
                interests = self.generate_fake_interests(
                    reg_id, start_time, stop_time, interval_sec=0)
        else:
            logger.info("Found saved interests in json")
            interests = interest_saved
        return interests

    def generate_fake_interests(self, reg_id, start_time, end_time,
                                interval_sec=30):
        logger.debug(f"{reg_id}. Generating fake interests in time range "
                     f"from {start_time} to {end_time}")
        start_time_dt = datetime.datetime.strptime(start_time,
                                                   "%Y-%m-%d %H:%M:%S")
        end_time_dt = datetime.datetime.strptime(end_time,
                                                 "%Y-%m-%d %H:%M:%S")
        if interval_sec:
            time_splits = main_funcs.split_time_range_to_dicts(
                start_time_dt, end_time_dt,
                datetime.timedelta(seconds=interval_sec))
        else:
            time_splits = [{"time_start": start_time_dt,
                            "time_end": end_time_dt}]
        interests = []
        for split in time_splits:
            time_start = split["time_start"]
            time_end = split["time_end"]
            interests.append({
                "name": f"{reg_id}_"
                        f"{time_start.year}."
                        f"{time_start.month}."
                        f"{time_start.day} "
                        f"{time_start.hour}-"
                        f"{time_start.minute}-"
                        f"{time_start.second}_"
                        f"{time_end.hour}-"
                        f"{time_end.minute}-"
                        f"{time_end.second}",
                "start_time": time_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": time_end.strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": reg_id,
                "beg_sec": cms_api_funcs.seconds_since_midnight(time_start),
                "end_sec": cms_api_funcs.seconds_since_midnight(time_end),
                "year": time_start.year,
                "month": time_start.month,
                "day": time_start.day,
            })
        logger.debug(f"{reg_id}. Got {len(interests)} fake interests.")
        return interests

    async def download_reg_videos(self, reg_id, chanel_id: int = None,
                            start_time=None, end_time=None,
                            by_trigger=False, proc=False, split: int = None):
        logger.debug(f"Начинаем работу с устройством {reg_id}")
        begin_time = datetime.datetime.now()

        # Проверка доступности регистратора
        if not self.check_if_reg_online(reg_id):
            logger.info(f"{reg_id} недоступен.")
            return

        # Получаем информацию о регистраторе
        reg_info = main_funcs.get_reg_info(
            reg_id) or main_funcs.create_new_reg(reg_id)
        chanel_id = reg_info.get("chanel_id",
                                 0)  # Если нет ID канала, ставим 0

        start_time = start_time or main_funcs.get_reg_last_upload_time(reg_id)

        end_time = end_time or begin_time.strftime("%Y-%m-%d %H:%M:%S")

        # Разбиваем длинные интервалы на отрезки
        time_difference = (
                    datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") -
                    datetime.datetime.strptime(start_time,
                                               "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_difference > 3600:
            end_time = (datetime.datetime.strptime(start_time,
                                                   "%Y-%m-%d %H:%M:%S") +
                        datetime.timedelta(seconds=3600)).strftime(
                "%Y-%m-%d %H:%M:%S")
            print(end_time)

        logger.info(f"{reg_id} Начало: {start_time}, Конец: {end_time}")

        if reg_info["continuous"]:
            by_trigger = False
        # Определяем интересные интервалы
        interests = self.get_interests(reg_id, start_time, end_time,
                                       by_trigger)
        if not interests:
            logger.info("Нет интервалов интересов.")
            main_funcs.save_new_reg_last_upload_time(reg_id,
                                                     end_time)
            return

        # Загружаем видео
        await cms_api.download_interest_videos(self.jsession, interests,
                                               chanel_id, split)

        # Обрабатываем загруженные файлы
        await self.process_and_upload_videos_async(reg_id, interests)

        # Обновляем `last_upload_time`
        last_interest_time = self.get_last_interest_datetime(
            interests) if interests else end_time
        main_funcs.save_new_reg_last_upload_time(reg_id, last_interest_time)
        logger.info(
            f"{reg_id} Обновлен `last_upload_time`: {last_interest_time}")

    async def process_and_upload_videos_async(self, reg_id, interests):
        logger.info(
            f"{reg_id}: Начинаем асинхронную обработку {len(interests)} видео.")

        for interest in interests:
            interest_name = interest["name"]
            file_paths = interest.get("file_paths", [])
            if not file_paths:
                logger.warning(
                    f"{reg_id}: Нет видеофайлов для {interest_name}. Пропускаем.")
                continue

            if settings.config.getboolean("General", "pics_before_after"):
                # Запускаем скачивание фото и обработку видео ПАРАЛЛЕЛЬНО
                alarm_pictures_task = asyncio.create_task(
                    self.get_alarm_pictures_async(
                        reg_id,
                        interest["beg_sec"],
                        interest["end_sec"],
                        interest["year"],
                        interest["month"],
                        interest["day"]
                    )
                )

            video_task = asyncio.create_task(
                self.process_video_and_return_path(reg_id, interest,
                                                   file_paths)
            )

            # Дожидаемся завершения обеих задач
            alarm_pictures = await alarm_pictures_task
            output_video_path = await video_task

            if not output_video_path:
                logger.warning(
                    f"{reg_id}: Видео не было обработано. Пропускаем загрузку.")
                continue

            # Загружаем видео + фото тревоги в облако
            logger.info(
                f"{reg_id}: Загружаем {interest_name} в облако с фото тревоги.")
            upload_status = await asyncio.to_thread(
                cloud_uploader.upload_file, output_video_path,
                settings.CLOUD_PATH, pics=alarm_pictures
            )

            if upload_status:
                logger.info(
                    f"{reg_id}: Загрузка прошла успешно. Удаляем локальный файл.")
                os.remove(output_video_path)
            else:
                logger.error(f"{reg_id}: Ошибка загрузки {interest_name}.")

        logger.info(f"{reg_id}: Обработка завершена.")

    async def process_video_and_return_path(self, reg_id, interest,
                                            file_paths):
        """Обрабатывает видео и возвращает путь к финальному файлу."""
        logger.info(
            f"{reg_id}: Начинаем обработку видео для {interest['name']}.")

        interest_name = interest["name"]
        interest_temp_folder = os.path.join(settings.TEMP_FOLDER,
                                            interest_name)
        os.makedirs(interest_temp_folder, exist_ok=True)

        converted_videos = []
        for video_path in file_paths:
            if not os.path.exists(video_path):
                logger.warning(
                    f"{reg_id}: Файл {video_path} не найден. Пропускаем.")
                continue

            logger.info(
                f"{reg_id}: Конвертация {video_path} в {self.output_format}.")
            converted_video = main_funcs.process_video_file(video_path)

            if converted_video:
                converted_videos.append(converted_video)
                os.remove(
                    video_path)  # Удаляем исходный файл после конвертации

        # Объединяем видео, если их несколько
        if len(converted_videos) > 1:
            output_video_path = os.path.join(
                settings.INTERESTING_VIDEOS_FOLDER,
                f"{interest_name}.{self.output_format}")
            await asyncio.to_thread(main_funcs.concatenate_videos,
                                    converted_videos, output_video_path)

            # Удаляем временные файлы после объединения
            shutil.rmtree(interest_temp_folder)
            for file in converted_videos:
                os.remove(file)

        elif len(converted_videos) == 1:
            output_video_path = converted_videos[
                0]  # Если одно видео, просто используем его

        else:
            logger.warning(f"{reg_id}: После обработки не осталось видео.")
            return None  # Возвращаем None, если видео не обработано

        return output_video_path

    def get_alarm_pictures(self, reg_id, beg_sec, end_sec, year: int,
                           month: int, day: int, channels: list = None):
        # Синхронная обертка для асинхронного метода
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Если event loop уже запущен, используем его
            return loop.run_until_complete(
                self.get_alarm_pictures_async(reg_id, beg_sec, end_sec, year,
                                              month, day, channels))
        else:
            # Если event loop не запущен, создаем новый
            return asyncio.run(
                self.get_alarm_pictures_async(reg_id, beg_sec, end_sec, year,
                                              month, day, channels))

    async def get_alarm_pictures_async(self, reg_id, beg_sec, end_sec,
                                       year: int,
                                       month: int, day: int,
                                       channels: list = None):
        """
        Получает картинки до и после события для заданных каналов.

        :param reg_id: ID регистратора.
        :param beg_sec: Начало временного интервала (в секундах).
        :param end_sec: Конец временного интервала (в секундах).
        :param year: Год.
        :param month: Месяц.
        :param day: День.
        :param channels: Список каналов. Если не указан, используются (0, 1, 2, 3).
        :return: Словарь с картинками до и после события.
        """
        logger.debug("Getting pictures")
        if not channels:
            channels = (0, 1, 2, 3)
        try:
            # Получаем картинки до события
            response_before = cms_api.get_video(
                self.jsession,
                device_id=reg_id,
                start_time_seconds=beg_sec - 10,
                end_time_seconds=beg_sec + 10,
                year=year,
                month=month,
                day=day,
                chanel_id=0,
                fileattr=1
            ).json()
            chanel_pics_before = await cms_api.fetch_photo_url(
                response_before["files"], channels)
            # Получаем картинки после события
            response_after = cms_api.get_video(
                self.jsession,
                device_id=reg_id,
                start_time_seconds=end_sec - 10,
                end_time_seconds=end_sec + 10,
                year=year,
                month=month,
                day=day,
                chanel_id=0,
                fileattr=1
            )
            chanel_pics_after = await cms_api.fetch_photo_url(
                response_after["files"], channels)
            logger.debug("Pictures retrieved successfully")
            return {
                "chanel_pics_before": chanel_pics_before,
                "chanel_pics_after": chanel_pics_after
            }
        except Exception as e:
            logger.error(f"Error while getting pictures: {e}")
            return {
                "chanel_pics_before": {},
                "chanel_pics_after": {}
            }

    def get_last_interest_datetime(self, interests):
        last_interest = interests[-1]
        return last_interest["end_time"]

    def upload_interest_video_to_cloud(self, interest_path,
                                       destination=None, pics=None):
        if not destination:
            destination = settings.CLOUD_PATH
        return cloud_uploader.upload_file(interest_path, destination,
                                          pics=pics)

    async def mainloop(self):
        logger.info("Mainloop has been launched with success.")
        while True:
            devices_online = self.get_devices_online()
            for device_dict in devices_online:
                reg_id = device_dict["vid"]
                print(reg_id)
                await self.operate_device(reg_id)
            await asyncio.sleep(5)

    def check_if_reg_online(self, reg_id):
        devices_online = self.get_devices_online()
        for device_dict in devices_online:
            if reg_id == device_dict["vid"]:
                return True

    def trace_reg_state(self, reg_id):
        online_was = False
        bat_discharge_was = 0
        while True:
            device_status = self.get_devices_online()
            if not device_status:
                online_cur = 0
            else:
                online_cur = device_status[0]["online"]
            if online_cur != online_was:
                logger.info(f"Reg {reg_id} status has changed! "
                            f"(Was {online_was} to {online_cur})")
                online_was = online_cur
            if online_cur:
                status = cms_api.get_device_status(self.jsession, reg_id)
                status_json = status.json()
                if not status_json["result"] == 0:
                    logger.error(f"Get device status error: {status_json}")
                status = status_json["status"][0]
                s1_status = cms_api_funcs.analyze_s1(status["s1"])
                bat_discharge_status = s1_status["io1"]
                if bat_discharge_status != bat_discharge_was:
                    logger.info(
                        f"Bat discharge status changed! "
                        f"({bat_discharge_was} to {bat_discharge_status})")
            time.sleep(3)


if __name__ == "__main__":
    d = Main()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(d.mainloop())

    # d.download_reg_videos(
    #    "2024050601",
    #    chanel_id=0,
    #    start_time="2025-02-20 11:10:00",
    #    end_time="2025-02-20 11:16:00",
    #    by_trigger=False,
    #    split=120)
    # b = d.trace_reg_state("104039")
    # 118270348452
    # 2024050601
