import os
import logging
from datetime import datetime
from django.conf import settings

class WeeklyMonthFileHandler(logging.Handler):
    def __init__(self, base_dir=None, mode='a', encoding='utf-8'):
        super().__init__()
        self.base_dir = base_dir or os.path.join(settings.BASE_DIR, 'logs')
        self.mode = mode
        self.encoding = encoding
        self._current_file = None
        self._current_stream = None

    def _get_log_filepath(self):
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        
        # Calculate week of the month (1 to 5)
        day = now.day
        week_of_month = (day - 1) // 7 + 1
        
        folder_path = os.path.join(self.base_dir, year, month)
        os.makedirs(folder_path, exist_ok=True)
        
        file_name = f'week_{week_of_month}.log'
        return os.path.join(folder_path, file_name)

    def emit(self, record):
        try:
            msg = self.format(record)
            filepath = self._get_log_filepath()
            
            # Check if we need to open a new file (e.g. day/week changed)
            if self._current_file != filepath:
                if self._current_stream:
                    self._current_stream.close()
                self._current_file = filepath
                self._current_stream = open(filepath, self.mode, encoding=self.encoding)
            
            self._current_stream.write(msg + '\n')
            self._current_stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        if self._current_stream:
            self._current_stream.close()
        super().close()

