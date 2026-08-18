# Fixture scaffold — NOT an unmodified upstream copy.
#
# Provides just enough of vllm.logger for vllm.utils.import_utils to import
# standalone, without a full vLLM installation. See demo/SOURCE.md.

import logging


def init_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
