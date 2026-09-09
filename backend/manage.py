"""Account management from the command line.

    py -m backend.manage list
    py -m backend.manage add <username> <role>     # prompts for a password
    py -m backend.manage passwd <username>         # prompts for a new password
    py -m backend.manage delete <username>

Roles: superadmin, trademark_admin, drafter
"""

import getpass
import sys

from . import auth, db, roles

MIN_PASSWORD = 8


def _prompt_password(label="Password", username=None):
    first = getpass.getpass("%s: " % label)
    if len(first) < MIN_PASSWORD:
        print("Password must be at least %d characters." % MIN_PASSWORD)
        return None
    weak_reason = auth.is_weak_password(first, username)
    if weak_reason:
        print(weak_reason)
        return None
    if first != getpass.getpass("Confirm: "):
        print("Passwords did not match.")
        return None
    return first


def cmd_list():
    users = auth.list_users()
    if not users:
        print("No accounts yet.")
        return 0
    print("%-4s %-20s %-18s %-8s %s" % ("ID", "USERNAME", "ROLE", "ACTIVE", "CREATED"))
    for u in users:
        print("%-4s %-20s %-18s %-8s %s" % (
            u["id"], u["username"], u["role"],
            "yes" if u["active"] else "no", u["created_at"]))
    return 0


def cmd_add(username, role):
    if role not in roles.ALL_ROLES:
        print("Unknown role %r. Choose one of: %s" % (role, ", ".join(roles.ALL_ROLES)))
        return 2
    password = _prompt_password(username=username)
    if password is None:
        return 1
    if auth.create_user(username, password, role) is None:
        print("That username is already taken.")
        return 1
    print("Created %s (%s)." % (username, roles.ROLE_LABELS[role]))
    return 0


def cmd_passwd(username):
    if auth.get_user_by_name(username) is None:
        print("No such user: %s" % username)
        return 1
    password = _prompt_password("New password", username=username)
    if password is None:
        return 1
    auth.set_password(username, password)
    print("Password updated for %s." % username)
    return 0


def cmd_delete(username):
    user = auth.get_user_by_name(username)
    if user is None:
        print("No such user: %s" % username)
        return 1
    if user["role"] == roles.SUPERADMIN:
        remaining = [u for u in auth.list_users()
                     if u["role"] == roles.SUPERADMIN and u["id"] != user["id"]]
        if not remaining:
            print("Refusing to delete the only superadmin -- you would lock "
                  "yourself out of user management.")
            return 1
    auth.delete_user(user["id"])
    print("Deleted %s." % username)
    return 0


def main(argv):
    db.init_db()
    auth.init_auth_schema()

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    command, args = argv[0], argv[1:]
    if command == "list":
        return cmd_list()
    if command == "add" and len(args) == 2:
        return cmd_add(args[0], args[1])
    if command == "passwd" and len(args) == 1:
        return cmd_passwd(args[0])
    if command == "delete" and len(args) == 1:
        return cmd_delete(args[0])

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
