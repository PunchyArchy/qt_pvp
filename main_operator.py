import threading
import time
import traceback

from qt_pvp.cms_interface import functions as cms_api_funcs
from qt_pvp import functions as main_funcs
from qt_pvp.cms_interface import cms_api
from qt_pvp.logger import logger
from qt_pvp import settings
import datetime
import shutil
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
        logger.debug(f"Got devices online: {devices_online}")
        return devices_online

    def download_all(self, devices_online: [] = None):
        logger.info("Downloading from all regs")
        if not devices_online:
            devices_online = self.get_devices_online()
        for device_dict in devices_online:
            reg_id = device_dict["vid"]
            self.download_reg_videos(reg_id)

    def operate_device(self, reg_id):
        if reg_id in self.devices_in_progress:
            return
        self.devices_in_progress.append(reg_id)
        try:
            self.download_reg_videos(reg_id)
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
                stop_time=stop_time
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
                "device_id": reg_id, })
        logger.debug(f"{reg_id}. Got {len(interests)} fake interests.")
        return interests

    def download_reg_videos(self, reg_id, start_time=None, end_time=None,
                            by_trigger=False, proc=False, split: int = None):
        logger.debug(f"Working with device {reg_id}")
        begin_time = datetime.datetime.now()
        now = begin_time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.check_if_reg_online(reg_id):
            logger.info(f"{reg_id}. MDVR is offline")
            return
        reg_info = main_funcs.get_reg_info(reg_id=reg_id)
        if not reg_info:
            reg_info = main_funcs.create_new_reg(reg_id)
        if not start_time:
            start_time = main_funcs.get_reg_last_upload_time(reg_id)
        if not end_time:
            end_time = now
        logger.debug(f"{reg_id}. Start time: {start_time}")
        interests = self.get_interests(reg_id, start_time, end_time,
                                       by_trigger)
        if not interests:
            logger.info("No interests found")
            return
        interests_with_fp = []
        logger.info(f"{reg_id}. Generating and executing download tasks")
        cms_api.download_interest_videos(self.jsession, interests, split)
        #url = cms_api_funcs.form_add_download_task_url(reg_id=reg_id,
        #                                               start_timestamp=start_time,
        #                                               end_timestamp=end_time,
        #                                               channel_id=1)
        #print(url)
        interest_create_datetime = datetime.datetime.now()
        interest_create_seconds = (
                    interest_create_datetime - begin_time).seconds
        logger.info(f"{reg_id}. Getting downloaded videos...")
        for interest in interests:
            data = cms_api.get_interest_download_path(
                self.jsession, interest)
            interests_with_fp.append(data)
        download_time = datetime.datetime.now()
        download_seconds = (download_time - interest_create_datetime).seconds
        logger.info(f"{reg_id}. Downloading done. "
                    f"It take {download_seconds} seconds")
        for interest in interests_with_fp:
            interest_name = interest["name"]
            output_video_path = os.path.join(
                settings.INTERESTING_VIDEOS_FOLDER,
                f"{interest_name}.{self.output_format}")
            logger.info(f"{reg_id}. C&C interest {interest_name}")
            interest_temp_folder = os.path.join(
                settings.TEMP_FOLDER, interest_name)
            if not os.path.exists(interest_temp_folder):
                os.makedirs(interest_temp_folder)
            converted_videos = []
            if None in interest["file_paths"]:
                interest["file_paths"].remove(None)
            if not interest["file_paths"]:
                logger.error(
                    f"{reg_id}. Not found filepaths for interest "
                    f"{interest_name}")
                continue
            if len(interest["file_paths"]) > 1 and proc:
                logger.info(f"{reg_id}. Converting videos...")
                for video_path in interest["file_paths"]:
                    logger.info(f"Converting {video_path}")
                    converted_video = main_funcs.convert_video_file(
                        video_path, output_dir=interest_temp_folder,
                        output_format=self.output_format)
                    # os.remove(video_path)
                    if converted_video:
                        converted_videos.append(converted_video)
            else:
                # Видео только одно
                logger.info(
                    f"{reg_id}. Moving interest video to {output_video_path}")
                source = os.path.normpath(interest["file_paths"][0])
                shutil.copy(source, output_video_path)
            if converted_videos:
                logger.info("Concatenating videos...")
                main_funcs.concatenate_videos(
                    converted_files=converted_videos,
                    output_abs_name=output_video_path)
                logger.info(f"{reg_id} Success concatenated {interest_name} "
                            f"to {output_video_path}")
                shutil.rmtree(interest_temp_folder)
            else:
                logger.debug("No converted videos for concatenating found.")
        pvp_time_seconds = (datetime.datetime.now() - download_time).seconds
        main_funcs.save_new_reg_last_upload_time(reg_id, end_time)
        logger.info(f"{reg_id}. New last upload data - {end_time}")
        main_funcs.clean_interests(reg_id)
        self.video_ready_trigger()
        last = (datetime.datetime.now() - begin_time).seconds
        logger.info(
            f"{reg_id}. All works are done. "
            f"Interests creating take {interest_create_seconds} seconds."
            f"Downloading take {download_seconds} seconds."
            f"PvP operations {pvp_time_seconds} seconds."
            f"it take {last} seconds in total.")

    def mainloop(self):
        logger.info("Mainloop has been launched with success.")
        while True:
            devices_online = self.get_devices_online()
            for device_dict in devices_online:
                reg_id = device_dict["vid"]
                self.operate_device(reg_id)
            time.sleep(5)

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
    # d.mainloop()
    d.download_reg_videos("2024050601", "2025-02-19 18:32:00",
                          "2025-02-19 18:34:00", by_trigger=False,
                          split=120)
    # b = d.trace_reg_state("104039")
    # 118270348452
    # 2024050601