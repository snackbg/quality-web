from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


ROLE_LABELS = {
    "admin": "Quản trị viên",
    "staff": "Nhân viên vận hành",
    "viewer": "Chỉ xem",
}
ALL_ROLES = tuple(ROLE_LABELS)
WRITE_ROLES = ("admin", "staff")


def user_roles(user):
    if user.is_superuser:
        return set(ALL_ROLES)
    return set(user.groups.values_list("name", flat=True)).intersection(ROLE_LABELS)


def has_role(user, *roles):
    return user.is_authenticated and bool(user_roles(user).intersection(roles))


def role_required(*read_roles, write_roles=None):
    def decorate(view_func):
        @wraps(view_func)
        def check_role(request, *args, **kwargs):
            allowed_roles = read_roles
            if request.method not in {"GET", "HEAD", "OPTIONS"} and write_roles is not None:
                allowed_roles = write_roles
            if not has_role(request.user, *allowed_roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return login_required(check_role)

    return decorate
