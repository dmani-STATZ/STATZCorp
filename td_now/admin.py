from django.contrib import admin
from .models import Map, PathNode, BuildSpot, TowerType, EnemyType, Wave, WaveEnemy, TowerLevel, Campaign, CampaignStage, StageWave, StageWaveGroup


@admin.register(Map)
class MapAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "width_tiles", "height_tiles", "start_money", "start_lives")


@admin.register(PathNode)
class PathNodeAdmin(admin.ModelAdmin):
    list_display = ("id", "map", "order_index", "x", "y")
    list_filter = ("map",)


@admin.register(BuildSpot)
class BuildSpotAdmin(admin.ModelAdmin):
    list_display = ("id", "map", "x", "y")
    list_filter = ("map",)


@admin.register(TowerType)
class TowerTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "cost", "damage", "range", "fire_rate",
        "area_additional_targets", "area_damage_ratio", "area_range",
        "growth_cost_mult", "growth_damage_mult", "growth_range_mult", "growth_fire_rate_mult",
        "icon_shape", "icon_color", "icon_blink_color", "beam_color", "beam_width", "beam_dash",
    )


class TowerLevelInline(admin.TabularInline):
    model = TowerLevel
    extra = 0
    fields = (
        "level_number", "damage_multiplier", "range_multiplier", "fire_rate_multiplier", "cost_multiplier",
        "aoe_additional_targets", "aoe_damage_ratio", "aoe_range",
        "aoe2_additional_targets", "aoe2_damage_ratio", "aoe2_range",
    )


TowerTypeAdmin.inlines = [TowerLevelInline]


class StageWaveGroupInline(admin.TabularInline):
    model = StageWaveGroup
    extra = 0


@admin.register(StageWave)
class StageWaveAdmin(admin.ModelAdmin):
    list_display = ("id", "stage", "wave_number")
    inlines = [StageWaveGroupInline]


class StageWaveInline(admin.TabularInline):
    model = StageWave
    extra = 0


@admin.register(CampaignStage)
class CampaignStageAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "order_index", "map", "use_map_waves", "waves_to_play", "start_money_override", "start_lives_override")
    list_filter = ("campaign",)
    inlines = [StageWaveInline]


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "start_money", "start_lives")


@admin.register(EnemyType)
class EnemyTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "max_health", "speed", "bounty")


class WaveEnemyInline(admin.TabularInline):
    model = WaveEnemy
    extra = 0


@admin.register(Wave)
class WaveAdmin(admin.ModelAdmin):
    list_display = ("id", "map", "wave_number")
    list_filter = ("map",)
    inlines = [WaveEnemyInline]
