from django.contrib.auth.decorators import user_passes_test

def role_required(role, login_url=None):
    """
    Decorator for views that checks whether a user is member of a role.
    roles: a list or tuple of allowed roles or a str with a single allowed role
    """
    def check_roles(user):
        if isinstance(role, str):
            roles = (role,)
        else:
            roles = role
        return user.is_authenticated and user.role in roles
    return user_passes_test(check_roles, login_url=login_url)

def user_is_superuser(view_func):
    """Restricts view audience to superuser-only."""
    decorator = user_passes_test(
        lambda u: u.is_superuser
    )
    return decorator(view_func)
