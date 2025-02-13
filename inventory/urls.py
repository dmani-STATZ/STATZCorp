"""
URL configuration for STATZWeb project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from . import views as Inventoryviews

app_name = 'inventory'

urlpatterns = [
    path('delete-item-ajax/<int:pk>/', Inventoryviews.delete_item_ajax, name='delete_item_ajax'),
    path('autocomplete/nsn/', Inventoryviews.autocomplete_nsn, name='autocomplete_nsn'),
    path('autocomplete/description/', Inventoryviews.autocomplete_description, name='autocomplete_description'),
    path('autocomplete/manufacturer/', Inventoryviews.autocomplete_manufacturer, name='autocomplete_manufacturer'),
    path('', Inventoryviews.dashboard, name='dashboard'),
    path('add-item/', Inventoryviews.add_item, name='add_item'),
    path('edit-item/<int:pk>/', Inventoryviews.edit_item, name='edit_item'),
    path('delete-item/<int:pk>/', Inventoryviews.delete_item, name='delete_item'),
]
