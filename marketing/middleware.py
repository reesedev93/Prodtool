from django.utils.deprecation import MiddlewareMixin


class TrackRefererMiddleware(MiddlewareMixin):
    def __init__(self, get_response=None):
        super().__init__(get_response)

    def process_response(self, request, response):
        first_touch = request.COOKIES.get("first_landing_page", None)

        if not first_touch:
            # These cookies expire in 1 year
            url = f"{request.META.get('PATH_INFO', '')}?{request.META.get('QUERY_STRING','')}"
            response.set_cookie("first_landing_page", url, max_age=31536000)

            referer = request.META.get("HTTP_REFERER", None)
            response.set_cookie("first_referer", referer, max_age=31536000)

        last_touch = request.COOKIES.get("last_landing_page", None)
        if not last_touch:
            url = f"{request.META.get('PATH_INFO','')}?{request.META.get('QUERY_STRING','')}"

            # These cookies expire in 6h. So hitting Savio.io, staying on it for 6h+,
            # and then signing up would cause an inaccurate last-touch referer and
            # landing page.  I'm OK with that.
            response.set_cookie("last_landing_page", url, max_age=21600)

            referer = request.META.get("HTTP_REFERER", None)
            response.set_cookie("last_referer", referer, max_age=21600)

        return response
