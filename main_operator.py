from qt_pvp.cms_interface import functions as cms_api_funcs
from qt_pvp import functions as main_funcs
from qt_pvp.cms_interface import cms_api
from qt_pvp import cloud_uploader
from qt_pvp.logger import logger
from pathlib import Path
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

    def get_interests(self, reg_id, reg_info, start_time, stop_time):
        #interest_saved = main_funcs.get_interests(reg_id)
        #if not interest_saved:
        tracks = cms_api.get_device_track_all_pages(
            jsession=self.jsession,
            device_id=reg_id,
            start_time=start_time,
            stop_time=stop_time,
        )
        interests = cms_api_funcs.analyze_tracks_get_interests(
            tracks=tracks,
            by_stops=reg_info["by_stops"],
            continuous=reg_info["continuous"],
            by_lifting_limit_switch=reg_info["by_lifting_limit_switch"],

        )
        #main_funcs.save_new_interests(reg_id, interests)
        #else:
        #    logger.info("Found saved interests in json")
       #     interests = interest_saved
        return interests

    async def download_reg_videos(self, reg_id, chanel_id: int = None,
                                  start_time=None, end_time=None,
                                  by_trigger=False, proc=False,
                                  split: int = None):
        logger.debug(f"Начинаем работу с устройством {reg_id}")
        begin_time = datetime.datetime.now()

        # Проверка доступности регистратора
        if not self.check_if_reg_online(reg_id):
            logger.info(f"{reg_id} недоступен.")
            return

        # Получаем информацию о регистраторе
        reg_info = main_funcs.get_reg_info(
            reg_id) or main_funcs.create_new_reg(reg_id)
        logger.debug(f"Информация о регистраторе {reg_id} - {reg_info}")
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
        else:
            logger.debug(f"f{reg_id}. Time difference is too short "
                         f"({time_difference} сек.)")
            return
        logger.info(f"{reg_id} Начало: {start_time}, Конец: {end_time}")

        # Определяем интересные интервалы
        interests = self.get_interests(reg_id, reg_info, start_time, end_time)
        if not interests:
            logger.info("Нет интервалов интересов.")
            main_funcs.save_new_reg_last_upload_time(reg_id,
                                                     end_time)
            return

        for interest in interests:
            logger.info(f"Работаем с интересом {interest}")
            # Загружаем видео
            interest = await cms_api.download_interest_videos(
                self.jsession,
                interest,
                chanel_id, split)
            if not interest:
                logger.warning(
                    f"{reg_id}. Не найдены видео на канале {chanel_id}")
                continue

            await self.process_and_upload_videos_async(reg_id, interest)

            if settings.config.getboolean("General", "pics_before_after"):
                # Запускаем скачивание фото и обработку видео ПАРАЛЛЕЛЬНО
                frames_before = await cms_api.get_frames(
                    jsession=self.jsession, reg_id=reg_id,
                    year=interest["year"], month=interest["month"],
                    day=interest["day"],
                    start_sec=interest["photo_before_sec"],
                    end_sec=interest["photo_before_sec"] + 1)
                frames_after = await cms_api.get_frames(
                    jsession=self.jsession, reg_id=reg_id,
                    year=interest["year"], month=interest["month"],
                    day=interest["day"],
                    start_sec=interest["photo_after_sec"],
                    end_sec=interest["photo_after_sec"] + 1)
                logger.debug(f"Фото до - {frames_before}. "
                             f"Фото после - {frames_after}")
                upload_status = await asyncio.to_thread(
                    cloud_uploader.create_pics, interest["name"],
                    settings.CLOUD_PATH, frames_before, frames_after
                )

                if upload_status:
                    all_frames = frames_before + frames_after
                    for frame in all_frames:
                        logger.info(
                            f"{reg_id}: Загрузка прошла успешно. Удаляем локальные фото-файлы ({frame}).")
                        os.remove(frame)
                last_interest_time = self.get_last_interest_datetime(
                    interests)
                main_funcs.save_new_reg_last_upload_time(reg_id,
                                                         last_interest_time)
        # Обновляем `last_upload_time`
        last_interest_time = self.get_last_interest_datetime(
            interests) if interests else end_time
        main_funcs.save_new_reg_last_upload_time(reg_id, last_interest_time)


    async def process_and_upload_videos_async(self, reg_id, interest):
        interest_name = interest["name"]
        file_paths = interest.get("file_paths", [])
        if not file_paths:
            logger.warning(
                f"{reg_id}: Нет видеофайлов для {interest_name}. Пропускаем.")
            return

        video_task = asyncio.create_task(
            self.process_video_and_return_path(reg_id, interest,
                                               file_paths)
        )

        # Дожидаемся завершения обеих задач
        output_video_path = await video_task

        if not output_video_path:
            logger.warning(
                f"{reg_id}: Нечего выгружать на облако ({output_video_path}).")
            return

        # Загружаем видео
        logger.info(
            f"{reg_id}: Загружаем видео {interest_name} в облако.")
        upload_status = await asyncio.to_thread(
            cloud_uploader.upload_file, interest_name, output_video_path,
            settings.CLOUD_PATH
        )

        if upload_status:
            logger.info(
                f"{reg_id}: Загрузка прошла успешно. Удаляем локальный файл.")
            os.remove(output_video_path)
        else:
            logger.error(f"{reg_id}: Ошибка загрузки {interest_name}.")

    async def process_video_and_return_path(self, reg_id, interest,
                                            file_paths):
        """Обрабатывает видео и возвращает путь к финальному файлу."""
        logger.info(
            f"{reg_id}: Начинаем обработку видео {file_paths} для {interest['name']}.")
        interest_name = interest["name"]
        interest_temp_folder = os.path.join(settings.TEMP_FOLDER,
                                            interest_name)
        os.makedirs(interest_temp_folder, exist_ok=True)

        final_interest_video_name = os.path.join(
            settings.INTERESTING_VIDEOS_FOLDER,
            f"{interest_name}.{self.output_format}")

        converted_videos = []
        for video_path in file_paths:
            logger.debug(f"Работаем с {video_path}")
            if not os.path.exists(video_path):
                logger.warning(
                    f"{reg_id}: Файл {video_path} не найден. Пропускаем.")
                continue

            logger.info(
                f"{reg_id}: Конвертация {video_path} в {self.output_format}.")
            converted_video = main_funcs.process_video_file(
                video_path, final_interest_video_name)

            if converted_video:
                converted_videos.append(converted_video)
                if os.path.exists(video_path):
                    logger.info(f"{reg_id}. Удаляю исходный файл {video_path}")
                    os.remove(
                        video_path)  # Удаляем исходный файл после конвертации

        # Объединяем видео, если их несколько
        if len(converted_videos) > 1:
            await asyncio.to_thread(main_funcs.concatenate_videos,
                                    converted_videos,
                                    final_interest_video_name)

            # Удаляем временные файлы после объединения
            shutil.rmtree(interest_temp_folder)
            for file in converted_videos:
                if os.path.exists(file):
                    os.remove(file)

        elif len(converted_videos) == 1:
            output_video_path = converted_videos[
                0]  # Если одно видео, просто используем его
            os.rename(output_video_path,
                      final_interest_video_name)

        else:
            logger.warning(f"{reg_id}: После обработки не осталось видео.")
            return None  # Возвращаем None, если видео не обработано

        return final_interest_video_name

    def get_last_interest_datetime(self, interests):
        last_interest = interests[-1]
        return last_interest["end_time"]

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
