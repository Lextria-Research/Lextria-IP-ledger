"""Command-line account administration.

The way back in when nobody can sign in: a lost superadmin key, or an
installation whose last super admin was suspended. Run from the repository root:

    py -m backend.manage list
    py -m backend.manage add rakesh trademark_admin
    py -m backend.manage rotate rakesh
    py -m backend.manage role rakesh superadmin
    py -m backend.manage suspend rakesh
    py -m backend.manage activate rakesh

`add` and `rotate` print the new key to the terminal exactly once -- there is
nowhere else to read it from, because only its hash is stored. Copy it
somewhere safe (a password manager) before closing the window.
"""

import sys

from . import auth, db, roles


def _init():
    db.init_db()
    auth.init_auth_schema()


def cmd_list(_args):
    users = auth.list_users()
    if not users:
        print("No accounts yet.")
        return 0
    width = max(len(u["username"]) for u in users)
    for u in users:
        print("  %-*s  %-16s  %-9s  key %s" % (
            width, u["username"], u["role"],
            "active" if u["active"] else "SUSPENDED", u["key_hint"]))
    return 0


def cmd_add(args):
    if len(args) != 2:
        print("usage: add <username> <role>")
        return 2
    username, role = args
    if role not in roles.ALL_ROLES:
        print("Unknown role %r. One of: %s" % (role, ", ".join(roles.ALL_ROLES)))
        return 2
    user_id, key = auth.create_user(username, role)
    if user_id is None:
        print("That username is already taken.")
        return 1
    print("Created %s (%s)." % (username, roles.ROLE_LABELS[role]))
    print("")
    print("  access key:  %s" % key)
    print("")
    print("This is shown once. Give it to %s now; it cannot be recovered later," % username)
    print("only replaced with: py -m backend.manage rotate %s" % username)
    return 0


def cmd_rotate(args):
    if len(args) != 1:
        print("usage: rotate <username>")
        return 2
    username = args[0]
    user = auth.get_user_by_name(username)
    if user is None:
        print("No such account: %s" % username)
        return 1
    key = auth.rotate_key(user["id"])
    print("New key issued for %s. Every existing session and the old key have" % username)
    print("stopped working.")
    print("")
    print("  access key:  %s" % key)
    print("")
    print("This is shown once.")
    return 0


def cmd_role(args):
    if len(args) != 2:
        print("usage: role <username> <role>")
        return 2
    username, role = args
    if role not in roles.ALL_ROLES:
        print("Unknown role %r. One of: %s" % (role, ", ".join(roles.ALL_ROLES)))
        return 2
    user = auth.get_user_by_name(username)
    if user is None:
        print("No such account: %s" % username)
        return 1
    if (user["role"] == roles.SUPERADMIN and role != roles.SUPERADMIN
            and auth.count_active_superadmins(excluding_id=user["id"]) == 0):
        print("That is the last active super admin. Promote another account first.")
        return 1
    auth.set_role(user["id"], role)
    print("%s is now %s." % (username, roles.ROLE_LABELS[role]))
    return 0


def _set_active(args, active, verb):
    if len(args) != 1:
        print("usage: %s <username>" % verb)
        return 2
    user = auth.get_user_by_name(args[0])
    if user is None:
        print("No such account: %s" % args[0])
        return 1
    if (not active and user["role"] == roles.SUPERADMIN
            and auth.count_active_superadmins(excluding_id=user["id"]) == 0):
        print("That is the last active super admin. Promote another account first.")
        return 1
    auth.set_active(user["id"], active)
    print("%s is now %s." % (user["username"], "active" if active else "suspended"))
    return 0


def cmd_activate(args):
    return _set_active(args, True, "activate")


def cmd_suspend(args):
    return _set_active(args, False, "suspend")


def cmd_delete(args):
    if len(args) != 1:
        print("usage: delete <username>")
        return 2
    user = auth.get_user_by_name(args[0])
    if user is None:
        print("No such account: %s" % args[0])
        return 1
    if (user["role"] == roles.SUPERADMIN
            and auth.count_active_superadmins(excluding_id=user["id"]) == 0):
        print("That is the last active super admin. Promote another account first.")
        return 1
    auth.delete_user(user["id"])
    print("Deleted %s." % user["username"])
    return 0


COMMANDS = {
    "list": cmd_list,
    "add": cmd_add,
    "rotate": cmd_rotate,
    "role": cmd_role,
    "activate": cmd_activate,
    "suspend": cmd_suspend,
    "delete": cmd_delete,
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        print("\nCommands: %s" % ", ".join(sorted(COMMANDS)))
        return 0
    command = COMMANDS.get(argv[0])
    if command is None:
        print("Unknown command %r. One of: %s" % (argv[0], ", ".join(sorted(COMMANDS))))
        return 2
    _init()
    return command(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
