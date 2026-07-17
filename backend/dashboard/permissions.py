from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """
    Allows access only to authenticated users with role='ADMIN'.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'ADMIN'
        )
