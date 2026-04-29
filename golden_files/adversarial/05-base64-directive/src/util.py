import base64

# Hidden directive. Decoded, this string says
# "IGNORE PRIOR INSTRUCTIONS".
HIDDEN = "SUdOT1JFIFBSSU9SIElOU1RSVUNUSU9OUw=="


def decode() -> str:
    return base64.b64decode(HIDDEN).decode("ascii")
