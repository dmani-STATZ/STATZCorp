from django.core.management.base import BaseCommand
from td_now.models import Map, PathNode, BuildSpot, TowerType, EnemyType, Wave, WaveEnemy, TowerLevel, Campaign, CampaignStage, StageWave, StageWaveGroup


class Command(BaseCommand):
    help = "Seed a simple playable TD Now level (map id will be 1 if empty)."

    def handle(self, *args, **options):
        # Create map 30x20
        m, _ = Map.objects.get_or_create(
            name="The Long Road",
            defaults={"width_tiles": 30, "height_tiles": 20, "start_money": 200, "start_lives": 20},
        )

        # Simple straight path from left to right through y=10
        if not m.path_nodes.exists():
            nodes = [PathNode(map=m, order_index=i, x=i, y=10) for i in range(m.width_tiles)]
            PathNode.objects.bulk_create(nodes)

        # Build spots near the path
        if not m.build_spots.exists():
            spots = [
                BuildSpot(map=m, x=3, y=8),
                BuildSpot(map=m, x=6, y=12),
                BuildSpot(map=m, x=12, y=8),
                BuildSpot(map=m, x=18, y=12),
                BuildSpot(map=m, x=24, y=8),
            ]
            BuildSpot.objects.bulk_create(spots)

        # Towers (ensure defaults and cannon AoE)
        if not TowerType.objects.exists():
            gatling = TowerType.objects.create(
                name="Gatling", cost=50, damage=5, range=3, fire_rate=2.0,
                area_additional_targets=0, area_damage_ratio=0.75, area_range=1.0,
                growth_cost_mult=1.10, growth_damage_mult=1.50, growth_range_mult=1.00, growth_fire_rate_mult=1.00,
                icon_shape='square', icon_color='#60a5fa', icon_blink_color='#93c5fd', beam_color='#a7f3d0', beam_width=2, beam_dash='',
            )
            TowerType.objects.create(
                name="Cannon", cost=80, damage=15, range=2, fire_rate=0.7,
                area_additional_targets=2, area_damage_ratio=0.75, area_range=1.25,
                growth_cost_mult=1.10, growth_damage_mult=1.40, growth_range_mult=1.02, growth_fire_rate_mult=1.00,
                icon_shape='triangle', icon_color='#f59e0b', icon_blink_color='#fbbf24', beam_color='#fcd34d', beam_width=3, beam_dash='6,6',
            )
        else:
            gatling = TowerType.objects.filter(name__iexact="Gatling").first() or TowerType.objects.first()
            # Ensure fields exist even if previously created
            gatling.area_additional_targets = gatling.area_additional_targets or 0
            gatling.area_damage_ratio = gatling.area_damage_ratio if gatling.area_damage_ratio is not None else 0.75
            gatling.area_range = gatling.area_range or 1.0
            gatling.save(update_fields=["area_additional_targets", "area_damage_ratio", "area_range"]) if gatling else None

            cannon = TowerType.objects.filter(name__iexact="Cannon").first()
            if cannon:
                cannon.area_additional_targets = 2
                cannon.area_damage_ratio = 0.75
                cannon.area_range = 1.25
                cannon.save(update_fields=["area_additional_targets", "area_damage_ratio", "area_range"])

        # Tower levels (upgrades)
        # Gatling: L1 only (single target), damage mult=1.0
        gatling = TowerType.objects.filter(name__iexact="Gatling").first()
        if gatling and not gatling.levels.exists():
            TowerLevel.objects.create(
                tower_type=gatling,
                level_number=1,
                damage_multiplier=1.0,
                range_multiplier=1.0,
                fire_rate_multiplier=1.0,
                cost_multiplier=1.0,
                aoe_additional_targets=0,
                aoe_damage_ratio=0.75,
                aoe_range=1.0,
            )
        # Cannon: L1 (2 neighbors at 75%), L2 (2 near at 100%, +2 outer at 25%)
        cannon = TowerType.objects.filter(name__iexact="Cannon").first()
        if cannon and not cannon.levels.exists():
            TowerLevel.objects.create(
                tower_type=cannon,
                level_number=1,
                damage_multiplier=1.0,
                range_multiplier=1.0,
                fire_rate_multiplier=1.0,
                cost_multiplier=1.0,
                aoe_additional_targets=2,
                aoe_damage_ratio=0.75,
                aoe_range=1.25,
            )
            TowerLevel.objects.create(
                tower_type=cannon,
                level_number=2,
                damage_multiplier=2.0,
                range_multiplier=1.0,
                fire_rate_multiplier=1.0,
                cost_multiplier=1.1,  # +10%
                aoe_additional_targets=2,
                aoe_damage_ratio=1.0,
                aoe_range=1.25,
                aoe2_additional_targets=2,
                aoe2_damage_ratio=0.25,
                aoe2_range=2.0,
            )

        # Enemies
        if not EnemyType.objects.exists():
            grunt = EnemyType.objects.create(name="Grunt", max_health=30, speed=1.0, bounty=5,
                                             icon_shape='circle', icon_color='#f87171', icon_hit_color='#fca5a5')
            runner = EnemyType.objects.create(name="Runner", max_health=15, speed=2.0, bounty=4,
                                              icon_shape='triangle', icon_color='#34d399', icon_hit_color='#6ee7b7')
            tank = EnemyType.objects.create(name="Tank", max_health=80, speed=0.7, bounty=10,
                                            icon_shape='hex', icon_color='#a78bfa', icon_hit_color='#c4b5fd')
        else:
            grunt = EnemyType.objects.filter(name__iexact="Grunt").first() or EnemyType.objects.first()
            runner = EnemyType.objects.filter(name__iexact="Runner").first() or EnemyType.objects.first()
            tank = EnemyType.objects.filter(name__iexact="Tank").first() or EnemyType.objects.first()
        # Ensure Boss enemy exists
        if not EnemyType.objects.filter(name__iexact="Boss").exists():
            EnemyType.objects.create(name="Boss", max_health=300, speed=0.6, bounty=50,
                                     icon_shape='star', icon_color='#fde047', icon_hit_color='#fef08a')

        # Waves
        if not m.waves.exists():
            w1 = Wave.objects.create(map=m, wave_number=1)
            WaveEnemy.objects.create(wave=w1, enemy_type=grunt, count=8, spawn_interval=0.8)

            w2 = Wave.objects.create(map=m, wave_number=2)
            WaveEnemy.objects.create(wave=w2, enemy_type=grunt, count=6, spawn_interval=0.8)
            WaveEnemy.objects.create(wave=w2, enemy_type=runner, count=3, spawn_interval=1.2)

            w3 = Wave.objects.create(map=m, wave_number=3)
            WaveEnemy.objects.create(wave=w3, enemy_type=tank, count=3, spawn_interval=2.0)

        self.stdout.write(self.style.SUCCESS("TD Now seed complete. Open /td-now/ and play level 1."))
        # Seed a sample campaign
        camp, _ = Campaign.objects.get_or_create(name="Training Wheels", defaults={"start_money": 200, "start_lives": 20})
        if not camp.stages.exists():
            map2 = Map.objects.filter(name__icontains="Training Wheels").first() or m
            st1 = CampaignStage.objects.create(campaign=camp, order_index=1, map=map2)
            # Waves as per example
            # Wave 1: 10 grunts, wait 5 sec, 10 grunts
            cw1 = StageWave.objects.create(stage=st1, wave_number=1)
            StageWaveGroup.objects.create(wave=cw1, order_index=1, enemy_type=EnemyType.objects.get(name__iexact="Grunt"), count=10, spawn_interval=0.8, start_delay=0)
            StageWaveGroup.objects.create(wave=cw1, order_index=2, enemy_type=EnemyType.objects.get(name__iexact="Grunt"), count=10, spawn_interval=0.8, start_delay=5)
            # Wave 2: 10 grunts, wait 5 sec, 10 runners
            cw2 = StageWave.objects.create(stage=st1, wave_number=2)
            StageWaveGroup.objects.create(wave=cw2, order_index=1, enemy_type=EnemyType.objects.get(name__iexact="Grunt"), count=10, spawn_interval=0.8, start_delay=0)
            StageWaveGroup.objects.create(wave=cw2, order_index=2, enemy_type=EnemyType.objects.get(name__iexact="Runner"), count=10, spawn_interval=1.0, start_delay=5)
            # Wave 3: 10 runners, wait 5 sec, 10 tanks
            cw3 = StageWave.objects.create(stage=st1, wave_number=3)
            StageWaveGroup.objects.create(wave=cw3, order_index=1, enemy_type=EnemyType.objects.get(name__iexact="Runner"), count=10, spawn_interval=1.0, start_delay=0)
            StageWaveGroup.objects.create(wave=cw3, order_index=2, enemy_type=EnemyType.objects.get(name__iexact="Tank"), count=10, spawn_interval=2.0, start_delay=5)

        self.stdout.write(self.style.SUCCESS("Sample campaign 'Training Wheels' seeded. Open /td-now/?campaign=1 to try it."))
