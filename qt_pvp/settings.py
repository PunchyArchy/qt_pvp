import configparser
import os

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER = os.path.join(CUR_DIR, "output")
INPUT_FOLDER = os.path.join(CUR_DIR, "input")
TESTS_FOLDER = os.path.join(CUR_DIR, "tests")
TEMP_FOLDER = os.path.join(CUR_DIR, "temp")
INTERESTING_VIDEOS_FOLDER = os.path.join(CUR_DIR, "interesting_videos")
TESTS_MISC_FOLDER = os.path.join(TESTS_FOLDER, "misc")
LOGS_DIR = os.path.join(CUR_DIR, "logs")
CONFIG_PATH = os.path.join(CUR_DIR, "config.cfg")

config = configparser.ConfigParser(
    inline_comment_prefixes='#',
    allow_no_value=True)
config.read(CONFIG_PATH)

states = os.sep.join((CUR_DIR, "states.json"))

eumid_host = f"http://{config.get('eumid', 'ip')}:" \
             f"{config.get('eumid', 'port')}/v1"
get_video_rout = f"{eumid_host}/video"
get_devices_rout = f"{eumid_host}/devices"
get_devices_online = f"{eumid_host}/analyze/online"
get_alarm_analyze = f"{eumid_host}/analyze/by_alarm"
add_download_task = f"{eumid_host}/StandardVideoTrackAction_addDownloadTask.action"

cms_host = f"{config.get('CMS', 'schema')}{config.get('CMS', 'ip')}:" \
           f"{config.getint('CMS', 'port')}"
