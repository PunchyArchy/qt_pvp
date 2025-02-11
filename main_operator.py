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
        logger.info(f"Got devices online: {devices_online}")
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
                    reg_id, start_time, stop_time, interval_sec=120)
        else:
            logger.info("Found saved interests in json")
            interests = interest_saved
        return interests

    def generate_fake_interests(self, reg_id, start_time, end_time,
                                interval_sec=120):
        logger.debug(f"{reg_id}. Generating fake interests in time range "
                     f"from {start_time} to {end_time}")
        time_splits = main_funcs.split_time_range_to_dicts(
            start_time, end_time, datetime.timedelta(seconds=interval_sec))
        interests = []
        for slit in time_splits:
            time_start = slit["time_start"]
            time_end = slit["time_end"]
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
                            by_trigger=False):
        logger.debug(f"Working with device {reg_id}")
        begin_time = datetime.datetime.now()
        now = begin_time.strftime("%Y-%m-%d %H:%M:%S")
        if not start_time:
            start_time = main_funcs.get_reg_last_upload_time(reg_id)
        if not end_time:
            end_time = now
        logger.debug(f"{reg_id}. Start time: {start_time}")
        interests = self.get_interests(reg_id, start_time, end_time,
                                       by_trigger)
        interests_with_fp = []
        logger.info(f"{reg_id}. Generating and executing download tasks")
        cms_api.download_interest_videos(self.jsession, interests)
        interest_create_datetime = datetime.datetime.now()
        interest_create_seconds = (interest_create_datetime - begin_time).seconds
        logger.info(f"{reg_id}. Getting downloaded videos...")
        for interest in interests:
            data = cms_api.get_interest_download_path(self.jsession,
                                                      interest)
            interests_with_fp.append(data)
        download_time = datetime.datetime.now()
        download_seconds = (download_time - interest_create_datetime).seconds
        logger.info(f"{reg_id}. Downloading done. "
                    f"It take {download_seconds} seconds")
        logger.info(f"{reg_id}. Converting&Concatenating videos...")
        for interest in interests_with_fp:
            interest_name = interest["name"]
            logger.info(f"{reg_id} C&C interest {interest_name}")
            interest_temp_folder = os.path.join(
                settings.TEMP_FOLDER, interest_name)
            if not os.path.exists(interest_temp_folder):
                os.makedirs(interest_temp_folder)
            converted_videos = []
            for video_path in interest["file_paths"]:
                if not video_path:
                    continue
                converted_video = main_funcs.convert_video_file(
                    video_path, output_dir=interest_temp_folder,
                    output_format=self.output_format)
                # os.remove(video_path)
                if converted_video:
                    converted_videos.append(converted_video)
            output_video_path = os.path.join(
                settings.INTERESTING_VIDEOS_FOLDER,
                f"{interest_name}.{self.output_format}")
            if converted_videos:
                main_funcs.concatenate_videos(
                    converted_files=converted_videos,
                    output_abs_name=output_video_path)
                logger.info(f"{reg_id} Success converted {interest_name} "
                            f"to {output_video_path}")
                shutil.rmtree(interest_temp_folder)
            else:
                logger.error("No converted video for concatenating found.")
        pvp_time_seconds = (datetime.datetime.now() - download_time).seconds
        main_funcs.save_new_reg_last_upload_time(reg_id, end_time)
        logger.info(f"{reg_id}. New last upload data - {end_time}")
        main_funcs.clean_interests(reg_id)
        self.video_ready_trigger()
        last = (begin_time - datetime.datetime.now()).seconds
        logger.info(f"{reg_id}. All works are done. "
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


if __name__ == "__main__":
    d = Main()
    # d.mainloop()
    d.download_reg_videos("104040", "2025-02-05 15:00:00",
                          "2025-02-05 16:00:00", by_trigger=False)
