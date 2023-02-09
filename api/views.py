from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from appaccounts.models import AppUser
from feedback.models import FeatureRequest, Feedback, FeedbackTemplate

from .serializers import (
    AppUserSerializer,
    ChromeExtensionFeedbackSerializer,
    DetailedFeedbackSerializer,
    FeatureRequestSerializer,
    FeedbackSerializer,
    OneShotFeedbackSerializer,
)


class CreateListRetrieveViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    A viewset that provides `retrieve`, `create`, and `list` actions.

    To use it, override the class and set the `.queryset` and
    `.serializer_class` attributes.
    """

    pass


class ListRetrieveViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet,
):
    """
    A viewset that provides `retrieve`, `create`, and `list` actions.

    To use it, override the class and set the `.queryset` and
    `.serializer_class` attributes.
    """

    pass


# class ListRetrieveViewSet(mixins.ListModelMixin,
#                             mixins.RetrieveModelMixin,
#                             viewsets.GenericViewSet):
#     """
#     A viewset that provides `retrieve` and `list` actions.

#     To use it, override the class and set the `.queryset` and
#     `.serializer_class` attributes.
#     """
#     pass

# class AccountUserViewSet(ListRetrieveViewSet):
#     serializer_class = UserSerializer
#     filter_backends = (filters.SearchFilter,)
#     search_fields = ('first_name', 'last_name', 'email')
#     permission_classes = (permissions.IsAuthenticated,)

#     def get_queryset(self):
#         return User.objects.filter(customer=self.request.user.customer)


class AppUserViewSet(CreateListRetrieveViewSet):
    serializer_class = AppUserSerializer
    filter_backends = (filters.SearchFilter,)
    search_fields = ("name", "email")
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return AppUser.objects.filter(customer=self.request.user.customer)


class FeedbackViewSet(ListRetrieveViewSet):
    serializer_class = FeedbackSerializer
    filter_backends = (filters.SearchFilter,)
    search_fields = ("problem", "solution", "user__company__name")
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)


class DetailedFeedbackViewSet(ListRetrieveViewSet):
    serializer_class = DetailedFeedbackSerializer
    filter_backends = (filters.SearchFilter,)
    search_fields = ("problem", "solution", "user__company__name")
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)


class FeatureRequestViewSet(ListRetrieveViewSet):
    serializer_class = FeatureRequestSerializer
    filter_backends = (filters.SearchFilter,)
    search_fields = (
        "title",
        "description",
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return FeatureRequest.objects.filter(customer=self.request.user.customer)


@csrf_exempt
@api_view(
    ["POST",]
)
@permission_classes((permissions.IsAuthenticated,))
def chrome_extension_create_feedback(request):
    serializer = ChromeExtensionFeedbackSerializer(
        data=request.data, context={"request": request}
    )
    if serializer.is_valid():
        return Response(serializer.save(), status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(
    ["POST",]
)
@parser_classes([JSONParser])
@permission_classes((permissions.IsAuthenticated,))
def create_feedback(request):
    print(request.data)
    serializer = OneShotFeedbackSerializer(
        data=request.data, context={"request": request}
    )
    if serializer.is_valid():
        return Response(serializer.save(), status=status.HTTP_201_CREATED)
    print(serializer.errors)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(
    ["GET",]
)
@permission_classes((permissions.IsAuthenticated,))
def check_user_auth(request):
    print(request.data)
    # Perhaps fail if sub is inactive. Downside here is a that they will lose their
    # data if their sub innocently goes inactive. Maybe it's best to just let it go.
    # So what if they create data they can't access?
    # if sub and sub.inactive():
    #     return JsonResponse({"detail": "You subscription is inactive. Login to https://www.savio.io to correct or contact support."}, status=403)
    # else:
    #     return JsonResponse({"detail": "Authenticated successfully"}, status=200)
    data = {
        "detail": "Authenticated successfully",
        "first_name": request.user.first_name,
        "last_name": request.user.last_name,
        "customer_name": request.user.customer.name,
        "email": request.user.email,
        "id": request.user.id,
    }

    return JsonResponse(data)


@api_view(
    ["GET",]
)
@permission_classes((permissions.IsAuthenticated,))
def get_user_from_auth_token(request):

    # This method returns data / settings to background.js in the Chrome Extension so the CE experience
    # can be customized.  Examples: user permissions around being able to create feature
    # requests from the CE, and the problem template.

    try:
        ft = FeedbackTemplate.objects.get(customer_id=request.user.customer.id).template
    except FeedbackTemplate.DoesNotExist:
        ft = ""

    data = {
        "id": request.user.id,
        "customer_name": request.user.customer.name,
        "email": request.user.email,
        "first_name": request.user.first_name,
        "last_name": request.user.last_name,
        "role": request.user.role,
        "permissions": request.user.get_permissions(),
        "problem_template": ft,
    }
    return Response(data)
