from .permissions import ALL_ROLES, ROLE_LABELS, has_role, user_roles


def access_context(request):
    user = request.user
    roles = user_roles(user) if user.is_authenticated else set()
    role_label = "Quản trị hệ thống" if user.is_superuser else next(
        (ROLE_LABELS[role] for role in ("admin", "staff", "viewer") if role in roles),
        "Chưa được phân quyền",
    )
    return {
        "access": {
            "role_label": role_label,
            "can_view_dashboard": has_role(user, *ALL_ROLES),
            "can_view_employees": has_role(user, "admin", "staff", "viewer"),
            "can_manage_employees": has_role(user, "admin", "staff"),
            "can_view_attendance": has_role(user, "admin", "staff", "viewer"),
            "can_scan_attendance": has_role(user, "admin", "staff"),
            "can_view_checkout": has_role(user, "admin", "staff", "viewer"),
            "can_scan_checkout": has_role(user, "admin", "staff"),
            "can_view_attendance_reports": has_role(user, "admin", "staff", "viewer"),
            "can_manage_leave_records": has_role(user, "admin", "staff"),
            "can_view_handovers": has_role(user, "admin", "staff", "viewer"),
            "can_manage_handovers": has_role(user, "admin", "staff"),
            "can_manage_access": has_role(user, "admin"),
        }
    }
