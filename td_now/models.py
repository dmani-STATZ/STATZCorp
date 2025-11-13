from django.db import models


class Map(models.Model):
    name = models.CharField(max_length=100)
    width_tiles = models.IntegerField(default=30)
    height_tiles = models.IntegerField(default=20)
    start_money = models.IntegerField(default=200)
    start_lives = models.IntegerField(default=20)

    def __str__(self):
        return f"{self.name} ({self.width_tiles}x{self.height_tiles})"


class PathNode(models.Model):
    map = models.ForeignKey(Map, on_delete=models.CASCADE, related_name='path_nodes')
    order_index = models.IntegerField()
    x = models.IntegerField()
    y = models.IntegerField()

    class Meta:
        ordering = ["order_index"]

    def __str__(self):
        return f"{self.map.name} node {self.order_index} ({self.x},{self.y})"


class BuildSpot(models.Model):
    map = models.ForeignKey(Map, on_delete=models.CASCADE, related_name='build_spots')
    x = models.IntegerField()
    y = models.IntegerField()

    def __str__(self):
        return f"BuildSpot {self.map.name} ({self.x},{self.y})"


class TowerType(models.Model):
    name = models.CharField(max_length=100)
    cost = models.IntegerField(default=50)
    damage = models.FloatField(default=5.0)
    range = models.FloatField(default=3.0, help_text="Range in tiles")
    fire_rate = models.FloatField(default=1.0, help_text="Shots per second")
    # Optional area/multi-hit settings (applied to additional targets around the primary)
    area_additional_targets = models.IntegerField(default=0, help_text="Number of extra enemies hit around the primary")
    area_damage_ratio = models.FloatField(default=0.75, help_text="Damage multiplier for additional targets (0..1)")
    area_range = models.FloatField(default=1.0, help_text="Radius in tiles around primary for additional targets")
    # Growth factors applied per level when no explicit TowerLevel overrides exist
    growth_cost_mult = models.FloatField(default=1.10, help_text="Per-level cost growth multiplier (e.g., 1.10 = +10%)")
    growth_damage_mult = models.FloatField(default=1.50, help_text="Per-level damage growth multiplier")
    growth_range_mult = models.FloatField(default=1.00, help_text="Per-level range growth multiplier")
    growth_fire_rate_mult = models.FloatField(default=1.00, help_text="Per-level fire-rate growth multiplier")
    # Visual customization
    icon_shape = models.CharField(max_length=20, default='square')
    icon_color = models.CharField(max_length=7, default='#60a5fa')
    icon_blink_color = models.CharField(max_length=7, default='#93c5fd', blank=True)
    beam_color = models.CharField(max_length=7, default='#a7f3d0', blank=True)
    beam_width = models.IntegerField(default=2)
    beam_dash = models.CharField(max_length=50, default='', blank=True, help_text='Comma-separated dash pattern, e.g., "6,6"')

    def __str__(self):
        return f"TowerType: {self.name} (${self.cost})"


class EnemyType(models.Model):
    name = models.CharField(max_length=100)
    max_health = models.FloatField(default=30.0)
    speed = models.FloatField(default=1.0, help_text="Tiles per second")
    bounty = models.IntegerField(default=5)
    # Visual customization
    icon_shape = models.CharField(max_length=20, default='circle')
    icon_color = models.CharField(max_length=7, default='#f87171')
    icon_hit_color = models.CharField(max_length=7, default='#fca5a5', blank=True)

    def __str__(self):
        return f"EnemyType: {self.name} (hp={self.max_health}, speed={self.speed})"


class Wave(models.Model):
    map = models.ForeignKey(Map, on_delete=models.CASCADE, related_name='waves')
    wave_number = models.IntegerField()

    class Meta:
        ordering = ["wave_number"]

    def __str__(self):
        return f"{self.map.name} - Wave {self.wave_number}"


class WaveEnemy(models.Model):
    wave = models.ForeignKey(Wave, on_delete=models.CASCADE, related_name='wave_enemies')
    enemy_type = models.ForeignKey(EnemyType, on_delete=models.CASCADE)
    count = models.IntegerField(default=1)
    spawn_interval = models.FloatField(default=1.0, help_text="Seconds between spawns")

    def __str__(self):
        return f"Wave {self.wave.wave_number}: {self.count}x {self.enemy_type.name}"


class TowerLevel(models.Model):
    tower_type = models.ForeignKey(TowerType, on_delete=models.CASCADE, related_name='levels')
    level_number = models.IntegerField()
    # Scaling
    damage_multiplier = models.FloatField(default=1.0, help_text="Damage is base damage * damage_multiplier")
    range_multiplier = models.FloatField(default=1.0, help_text="Range is base range * range_multiplier")
    fire_rate_multiplier = models.FloatField(default=1.0, help_text="Fire rate is base fire_rate * fire_rate_multiplier")
    cost_multiplier = models.FloatField(default=1.0, help_text="Cost for this level relative to base cost")
    # AoE ring 1 (neighbors near primary)
    aoe_additional_targets = models.IntegerField(default=0)
    aoe_damage_ratio = models.FloatField(default=0.75)
    aoe_range = models.FloatField(default=1.0)
    # AoE ring 2 (optional outer ring)
    aoe2_additional_targets = models.IntegerField(default=0)
    aoe2_damage_ratio = models.FloatField(default=0.25)
    aoe2_range = models.FloatField(default=0.0)

    class Meta:
        ordering = ["tower_type", "level_number"]
        unique_together = ("tower_type", "level_number")

    def __str__(self):
        return f"{self.tower_type.name} Lv {self.level_number}"


class Campaign(models.Model):
    name = models.CharField(max_length=100)
    start_money = models.IntegerField(default=200)
    start_lives = models.IntegerField(default=20)
    description = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Campaign: {self.name}"


class CampaignStage(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='stages')
    order_index = models.IntegerField()
    map = models.ForeignKey(Map, on_delete=models.CASCADE)
    # Optionally derive waves from Map if no custom waves are provided
    use_map_waves = models.BooleanField(default=False)
    waves_to_play = models.IntegerField(default=0, help_text='0 = all waves when using map waves')
    message = models.TextField(blank=True, default='')
    start_money_override = models.IntegerField(null=True, blank=True)
    start_lives_override = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["campaign", "order_index"]

    def __str__(self):
        return f"{self.campaign.name} - Stage {self.order_index} on {self.map.name}"


class StageWave(models.Model):
    stage = models.ForeignKey(CampaignStage, on_delete=models.CASCADE, related_name='waves')
    wave_number = models.IntegerField()

    class Meta:
        ordering = ["stage", "wave_number"]

    def __str__(self):
        return f"Stage {self.stage.order_index} Wave {self.wave_number}"


class StageWaveGroup(models.Model):
    wave = models.ForeignKey(StageWave, on_delete=models.CASCADE, related_name='groups')
    order_index = models.IntegerField(default=0)
    enemy_type = models.ForeignKey(EnemyType, on_delete=models.CASCADE)
    count = models.IntegerField(default=1)
    spawn_interval = models.FloatField(default=1.0)
    start_delay = models.FloatField(default=0.0, help_text='Seconds to wait before this group begins spawning')

    class Meta:
        ordering = ["wave", "order_index"]

    def __str__(self):
        return f"Group {self.order_index}: {self.count}x {self.enemy_type.name}"
