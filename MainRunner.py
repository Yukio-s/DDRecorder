import _thread
import datetime
import logging
import threading
import time
import traceback
from multiprocessing import Process, Value

import utils
from BiliLive import BiliLive
from BiliLiveRecorder import BiliLiveRecorder
from BiliVideoChecker import BiliVideoChecker
from DanmuRecorder import BiliDanmuRecorder
from Processor import Processor
from Uploader import Uploader


class MainRunner():
    def __init__(self, config):
        self.config = config
        self.prev_live_status = False
        self.current_state = Value(
            'i', int(utils.state.WAITING_FOR_LIVE_START))
        self.state_change_time = Value('f', time.time())
        if self.config['root']['enable_baiduyun']:
            from bypy import ByPy
            _ = ByPy()
        self.bl = BiliLive(self.config)
        self.blr = None
        self.bdr = None

    def proc(self, config: dict, record_dir: str, danmu_path: str, current_state, state_change_time) -> None:
        p = Processor(config, record_dir, danmu_path)
        p.run()

        if config['spec']['uploader']['record']['upload_record'] or config['spec']['uploader']['clips']['upload_clips']:
            current_state.value = int(utils.state.UPLOADING_TO_BILIBILI)
            state_change_time.value = time.time()
            u = Uploader(p.outputs_dir, p.splits_dir, config)
            d = u.upload(p.global_start)
            if not config['spec']['uploader']['record']['keep_record_after_upload'] and d.get("record", None) is not None:
                rc = BiliVideoChecker(d['record']['bvid'],
                                      p.splits_dir, config)
                rc.start()
            if not config['spec']['uploader']['clips']['keep_clips_after_upload'] and d.get("clips", None) is not None:
                cc = BiliVideoChecker(d['clips']['bvid'],
                                      p.outputs_dir, config)
                cc.start()

        if config['root']['enable_baiduyun'] and config['spec']['backup']:
            current_state.value = int(utils.state.UPLOADING_TO_BAIDUYUN)
            state_change_time.value = time.time()
            try:
                from bypy import ByPy
                bp = ByPy()
                bp.upload(p.merged_file_path)
            except Exception as e:
                logging.error('Error when uploading to Baiduyun:' +
                          str(e)+traceback.format_exc())

        if current_state.value != int(utils.state.LIVE_STARTED):
            current_state.value = int(utils.state.WAITING_FOR_LIVE_START)
            state_change_time.value = time.time()

    def run(self):
        try:
            while True:

                if not self.prev_live_status and self.bl.live_status:                 
                    start = datetime.datetime.now()
                    self.blr = BiliLiveRecorder(self.config, start)
                    self.bdr = BiliDanmuRecorder(self.config, start)
                    record_process = Process(
                        target=self.blr.run)
                    danmu_process = Process(
                        target=self.bdr.run)
                    danmu_process.start()
                    record_process.start()

                    self.current_state.value = int(utils.state.LIVE_STARTED)
                    self.state_change_time.value = time.time()
                    self.prev_live_status = True


                    record_process.join()
                    danmu_process.join()

                    self.current_state.value = int(utils.state.PROCESSING_RECORDS)
                    self.state_change_time.value = time.time()

                    self.prev_live_status = False
                    proc_process = Process(target=self.proc, args=(
                        self.config, self.blr.record_dir, self.bdr.log_filename, self.current_state, self.state_change_time))
                    proc_process.start()
                else:
                    time.sleep(self.config['root']['check_interval'])
        except KeyboardInterrupt:
            return
        except Exception as e:
            logging.error('Error in Mainrunner:' +
                          str(e)+traceback.format_exc())

class MainThreadRunner(threading.Thread):
    def __init__(self, config):
        threading.Thread.__init__(self)
        self.mr = MainRunner(config)

    def run(self):
        self.mr.run()