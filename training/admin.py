from django.contrib import admin
from .models import (
    Course,
    Account,
    Matrix,
    Tracker,
    ArcticWolfCourse,
    ArcticWolfCompletion,
    UserAccount,
    TrainingDoc,
)
from .forms import CourseForm, AccountForm, MatrixForm, TrainingDocForm
from django.contrib.auth.models import User


class TrainingDocInline(admin.TabularInline):
    model = TrainingDoc
    extra = 0
    form = TrainingDocForm
    fields = ("file", "file_name", "file_date", "uploaded_at")
    readonly_fields = ("file_name", "uploaded_at")


class CourseAdmin(admin.ModelAdmin):
    form = CourseForm
    list_display = ("name",)
    inlines = [TrainingDocInline]


class AccountAdmin(admin.ModelAdmin):
    form = AccountForm
    list_display = ("type",)


class MatrixAdmin(admin.ModelAdmin):
    form = MatrixForm
    list_display = ("account", "course", "frequency")
    fieldsets = (
        (
            None,
            {
                "fields": ("account", "course", "frequency"),
                "description": "Select the account type, the required training course, and the frequency for this requirement.",
            },
        ),
    )
    list_filter = ("account", "course", "frequency")
    search_fields = ("account__type", "course__name")


class UserAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "account")
    list_filter = ("account",)
    search_fields = ("user__username", "account__type")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


admin.site.register(Course, CourseAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(Matrix, MatrixAdmin)
admin.site.register(Tracker)
admin.site.register(ArcticWolfCourse)
admin.site.register(ArcticWolfCompletion)
admin.site.register(UserAccount, UserAccountAdmin)
