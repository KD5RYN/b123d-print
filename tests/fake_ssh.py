"""Stands in for `ssh` + sshd in tests: runs the forced command from an authorized_keys line the way
sshd does, with what the client asked for in SSH_ORIGINAL_COMMAND.

    B123D_PRINT_FAKE_SSH_FORCED='<command>' python tests/fake_ssh.py [ssh options] user@host [command words]
"""

import os
import sys

WITH_VALUE = set("BbcDEeFIiJLlmOoPpQRSWw")  # ssh options that take an argument

args = sys.argv[1:]
while args and args[0].startswith("-"):
    opt = args.pop(0)
    if len(opt) == 2 and opt[1] in WITH_VALUE:
        args.pop(0)
dest, words = args[0], args[1:]
env = dict(os.environ)
env.pop("SSH_ORIGINAL_COMMAND", None)
if words:
    env["SSH_ORIGINAL_COMMAND"] = " ".join(words)  # ssh joins the words with spaces, unquoted
env["SSH_CONNECTION"] = "127.0.0.1 50000 127.0.0.1 22"
os.execve("/bin/sh", ["/bin/sh", "-c", os.environ["B123D_PRINT_FAKE_SSH_FORCED"]], env)
