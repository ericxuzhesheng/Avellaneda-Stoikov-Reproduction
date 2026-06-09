"""Initialise Hummingbot's password verification file for headless runs.

Writes conf/.password_verification so `hummingbot_quickstart.py --headless -p ...`
can log in without the interactive first-run password prompt. Idempotent.

    PYTHONPATH=/home/hummingbot python data/init_password.py <password>
"""
import sys

from hummingbot.client.config.config_crypt import (
    ETHKeyFileSecretManger, store_password_verification,
)

pw = sys.argv[1] if len(sys.argv) > 1 else "aspass123"
store_password_verification(ETHKeyFileSecretManger(pw))
print("wrote conf/.password_verification")
