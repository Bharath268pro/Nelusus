import logging
import json
from opentelemetry import trace

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        current_span = trace.get_current_span()
        if current_span.is_recording():
            log_obj["trace_id"] = format(current_span.get_span_context().trace_id, "032x")
            log_obj["span_id"] = format(current_span.get_span_context().span_id, "016x")
        return json.dumps(log_obj)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.handlers = []
    logger.addHandler(handler)
