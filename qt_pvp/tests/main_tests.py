import datetime
import unittest


class TestCase(unittest.TestCase):
    def test_download(self):
        time_start = datetime.datetime.strptime(
            "2025.01.28 10:00:00", "%Y.%m.%d %H:%M:%S")
        time_stop = datetime.datetime.strptime(
            "2025.01.28 10:01:00", "%Y.%m.%d %H:%M:%S")
        device_id = "104040"
        channel_id = 0
        fname = None
        destination_folder = None
        response = main.download_video(
            time_start=time_start, time_stop=time_stop, device_id=device_id,
            channel=channel_id, name=fname,
            destination_folder=destination_folder)
        print(response)
