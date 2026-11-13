from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

from dashboard import views


urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("employees/", views.employees, name="employees"),
    path("attendance/", views.attendance, name="attendance"),
    path("checkout/", views.checkout, name="checkout"),
    path("attendance/reports/", views.attendance_reports, name="attendance-reports"),
    path("attendance/leave/", views.attendance_leave, name="attendance-leave"),
    path("attendance/status/", RedirectView.as_view(pattern_name="attendance-leave", query_string=True, permanent=False), name="attendance-statuses"),
    path("handovers/", views.handovers, name="handovers"),
    path("handovers/<int:handover_id>/status/", views.update_handover_status, name="handover-status"),
    path("access/", views.access_management, name="access-management"),
]
