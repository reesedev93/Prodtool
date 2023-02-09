from django.utils import timezone
from .models import OnboardingTask

def onboarding_status(request):
    if not request.user.is_anonymous and request.user.customer:
        percent_complete = OnboardingTask.objects.percent_complete(request.user.customer)

        has_incomplete_tasks = OnboardingTask.objects.filter(customer=request.user.customer, completed=False).exists()
        if has_incomplete_tasks:
            show_onboarding = True
        else:
            has_completed_tasks = OnboardingTask.objects.filter(customer=request.user.customer, completed=True).exists()
            if has_completed_tasks:
                most_recent_task_completion = OnboardingTask.objects.filter(customer=request.user.customer, completed=True).order_by("-updated")[0]
                td = timezone.now() - most_recent_task_completion.updated
                hours_since_last_task_completed = td.total_seconds() / 60 / 60
                if hours_since_last_task_completed > 2.0:
                    show_onboarding = False
                else:
                    show_onboarding = True
            else:
                show_onboarding = False
    else:
        percent_complete = 0.0
        show_onboarding = False
    return {
        'show_onboarding': show_onboarding,
        'percent_complete_as_float_onboarding_tasks': percent_complete,
        'percent_complete_onboarding_tasks': round(percent_complete*100),
    }
