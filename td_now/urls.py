from django.urls import path
from . import views

app_name = 'td_now'

urlpatterns = [
    # Landing: select campaign or single map
    path('', views.campaign_select, name='campaign_select'),
    # Game player
    path('play/', views.index, name='play'),
    path('api/levels/', views.levels_list, name='levels_list'),
    path('api/levels/<int:map_id>/', views.level_detail, name='level_detail'),
    path('api/campaigns/', views.campaigns_list, name='campaigns_list'),
    path('api/campaigns/<int:campaign_id>/', views.campaign_detail, name='campaign_detail'),
    path('api/campaigns/create/', views.create_campaign, name='create_campaign'),
    path('api/campaigns/<int:campaign_id>/update/', views.update_campaign, name='update_campaign'),
    path('builder/', views.builder, name='builder'),
    path('api/maps/', views.create_map, name='create_map'),
    path('api/maps/<int:map_id>/', views.update_map, name='update_map'),
    path('api/enemies/', views.enemies_list, name='enemies_list'),
    path('api/towers/', views.towers_list, name='towers_list'),
    path('api/towers/create/', views.towers_create, name='towers_create'),
    path('api/towers/<int:tower_id>/', views.towers_update, name='towers_update'),
    path('api/enemies/create/', views.enemies_create, name='enemies_create'),
    path('api/enemies/<int:enemy_id>/', views.enemies_update, name='enemies_update'),
    path('campaign-builder/', views.campaign_builder, name='campaign_builder'),
    path('assets/', views.asset_editor, name='asset_editor'),
]
