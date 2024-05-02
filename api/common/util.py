import copy
import logging
from common import TYPE_EFFICACY

def get_type_efficacy():
    logging.debug(TYPE_EFFICACY)
    return copy.deepcopy(TYPE_EFFICACY)