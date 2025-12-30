from enum import Enum

class UIProfile(str, Enum):
    MSK = "MSK"
    VASCULAR = "VASCULAR"
    ABDOMINAL = "ABDOMINAL"
    XRAY = "XRAY"
    CARDIO = "CARDIO"
