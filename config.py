import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Source and Target
SOURCE = XXXXXXXXXX
TARGET = XXXXXXXXXX

# Account pool — fill in your accounts here ONCE.
# Both login_accounts.py and AccountSwitch_Media_Forwarder.py read from this file.
ACCOUNTS = [
    {
        "name": "mrxyz",
        "api_id": XXXXXXXXX,
        "api_hash": "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "session": os.path.join(BASE_DIR, "session_mali"),
    },

]
