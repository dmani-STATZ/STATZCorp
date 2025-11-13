from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
from .models import Map, PathNode, BuildSpot, TowerType, EnemyType, Wave, WaveEnemy
from .models import Campaign, CampaignStage, StageWave, StageWaveGroup


def index(request):
    return render(request, 'td_now/index.html', {"title": "TD Now"})


def campaign_select(request):
    return render(request, 'td_now/campaign_select.html', {"title": "TD Now - Select"})


@login_required
def builder(request):
    return render(request, 'td_now/builder.html', {"title": "TD Now - Map Builder"})


@login_required
def campaign_builder(request):
    return render(request, 'td_now/campaign_builder.html', {"title": "TD Now - Campaign Builder"})


@login_required
def asset_editor(request):
    return render(request, 'td_now/asset_editor.html', {"title": "TD Now - Asset Editor"})


@require_GET
def levels_list(request):
    maps = Map.objects.all().values('id', 'name', 'width_tiles', 'height_tiles')
    return JsonResponse(list(maps), safe=False)


@require_GET
def enemies_list(request):
    items = [
        {
            'id': e.id,
            'name': e.name,
            'hp': e.max_health,
            'speed': e.speed,
            'bounty': e.bounty,
            'iconShape': e.icon_shape,
            'iconColor': e.icon_color,
            'iconHitColor': e.icon_hit_color,
        }
        for e in EnemyType.objects.all()
    ]
    return JsonResponse(items, safe=False)


@require_http_methods(["GET"])
def towers_list(request):
    items = [
        {
            'id': t.id,
            'name': t.name,
            'cost': t.cost,
            'damage': t.damage,
            'range': t.range,
            'fireRate': t.fire_rate,
            'iconShape': t.icon_shape,
            'iconColor': t.icon_color,
            'iconBlinkColor': t.icon_blink_color,
            'beamColor': t.beam_color,
            'beamWidth': t.beam_width,
            'beamDash': t.beam_dash,
        }
        for t in TowerType.objects.all()
    ]
    return JsonResponse(items, safe=False)


@require_http_methods(["POST"])
@login_required
def towers_create(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    t = TowerType.objects.create(
        name=data.get('name') or 'Tower',
        cost=int(data.get('cost') or 0),
        damage=float(data.get('damage') or 0),
        range=float(data.get('range') or 0),
        fire_rate=float(data.get('fireRate') or 0),
        icon_shape=data.get('iconShape') or 'square',
        icon_color=data.get('iconColor') or '#60a5fa',
        icon_blink_color=data.get('iconBlinkColor') or '#93c5fd',
        beam_color=data.get('beamColor') or '#a7f3d0',
        beam_width=int(data.get('beamWidth') or 2),
        beam_dash=data.get('beamDash') or '',
    )
    return JsonResponse({'id': t.id})


@require_http_methods(["PUT", "PATCH"])
@login_required
def towers_update(request, tower_id: int):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    t = get_object_or_404(TowerType, pk=tower_id)
    for k in ['name']:
        if k in data: setattr(t, k, data[k])
    if 'cost' in data: t.cost = int(data.get('cost') or 0)
    if 'damage' in data: t.damage = float(data.get('damage') or 0)
    if 'range' in data: t.range = float(data.get('range') or 0)
    if 'fireRate' in data: t.fire_rate = float(data.get('fireRate') or 0)
    if 'iconShape' in data: t.icon_shape = data.get('iconShape') or t.icon_shape
    if 'iconColor' in data: t.icon_color = data.get('iconColor') or t.icon_color
    if 'iconBlinkColor' in data: t.icon_blink_color = data.get('iconBlinkColor') or t.icon_blink_color
    if 'beamColor' in data: t.beam_color = data.get('beamColor') or t.beam_color
    if 'beamWidth' in data: t.beam_width = int(data.get('beamWidth') or t.beam_width)
    if 'beamDash' in data: t.beam_dash = data.get('beamDash') or t.beam_dash
    t.save()
    return JsonResponse({'id': t.id})


@require_http_methods(["POST"])
@login_required
def enemies_create(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    e = EnemyType.objects.create(
        name=data.get('name') or 'Enemy',
        max_health=float(data.get('hp') or 0),
        speed=float(data.get('speed') or 0),
        bounty=int(data.get('bounty') or 0),
        icon_shape=data.get('iconShape') or 'circle',
        icon_color=data.get('iconColor') or '#f87171',
        icon_hit_color=data.get('iconHitColor') or '#fca5a5',
    )
    return JsonResponse({'id': e.id})


@require_http_methods(["PUT", "PATCH"])
@login_required
def enemies_update(request, enemy_id: int):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    e = get_object_or_404(EnemyType, pk=enemy_id)
    for k in ['name']:
        if k in data: setattr(e, k, data[k])
    if 'hp' in data: e.max_health = float(data.get('hp') or 0)
    if 'speed' in data: e.speed = float(data.get('speed') or 0)
    if 'bounty' in data: e.bounty = int(data.get('bounty') or 0)
    if 'iconShape' in data: e.icon_shape = data.get('iconShape') or e.icon_shape
    if 'iconColor' in data: e.icon_color = data.get('iconColor') or e.icon_color
    if 'iconHitColor' in data: e.icon_hit_color = data.get('iconHitColor') or e.icon_hit_color
    e.save()
    return JsonResponse({'id': e.id})


@require_GET
def level_detail(request, map_id: int):
    m = get_object_or_404(Map, pk=map_id)
    path = list(PathNode.objects.filter(map=m).order_by('order_index').values('x', 'y'))
    build_spots = list(BuildSpot.objects.filter(map=m).values('x', 'y'))

    towers = []
    for t in TowerType.objects.all():
        levels = []
        for lvl in t.levels.all().order_by('level_number'):
            levels.append({
                "level": lvl.level_number,
                "damageMult": lvl.damage_multiplier,
                "rangeMult": lvl.range_multiplier,
                "fireRateMult": lvl.fire_rate_multiplier,
                "costMult": lvl.cost_multiplier,
                "aoe": {
                    "additionalTargets": lvl.aoe_additional_targets,
                    "damageRatio": lvl.aoe_damage_ratio,
                    "range": lvl.aoe_range,
                },
                "aoe2": {
                    "additionalTargets": lvl.aoe2_additional_targets,
                    "damageRatio": lvl.aoe2_damage_ratio,
                    "range": lvl.aoe2_range,
                },
            })
        towers.append({
            "id": t.id,
            "name": t.name,
            "cost": t.cost,
            "damage": t.damage,
            "range": t.range,
            "fireRate": t.fire_rate,
            "aoeAdditionalTargets": t.area_additional_targets,
            "aoeDamageRatio": t.area_damage_ratio,
            "aoeRange": t.area_range,
            "growth": {
                "cost": t.growth_cost_mult,
                "damage": t.growth_damage_mult,
                "range": t.growth_range_mult,
                "fireRate": t.growth_fire_rate_mult,
            },
            # icon visuals
            "iconShape": t.icon_shape,
            "iconColor": t.icon_color,
            "iconBlinkColor": t.icon_blink_color,
            "beamColor": t.beam_color,
            "beamWidth": t.beam_width,
            "beamDash": t.beam_dash,
            # omit legacy levels to simplify; growth + upgrades are used instead
        })
    enemies = [
        {
            "id": e.id,
            "name": e.name,
            "hp": e.max_health,
            "speed": e.speed,
            "bounty": e.bounty,
            "iconShape": e.icon_shape,
            "iconColor": e.icon_color,
            "iconHitColor": e.icon_hit_color,
        }
        for e in EnemyType.objects.all()
    ]

    waves_payload = []
    for w in Wave.objects.filter(map=m).order_by('wave_number'):
        enemies_def = [
            {
                "typeId": we.enemy_type_id,
                "count": we.count,
                "spawnInterval": we.spawn_interval,
            }
            for we in WaveEnemy.objects.filter(wave=w)
        ]
        waves_payload.append({
            "number": w.wave_number,
            "enemies": enemies_def,
        })

    payload = {
        "id": m.id,
        "name": m.name,
        "width": m.width_tiles,
        "height": m.height_tiles,
        "path": path,
        "buildSpots": build_spots,
        "startMoney": m.start_money,
        "startLives": m.start_lives,
        "towerTypes": towers,
        "enemyTypes": enemies,
        "waves": waves_payload,
    }
    return JsonResponse(payload)


@require_GET
def campaigns_list(request):
    items = Campaign.objects.all().values('id', 'name', 'start_money', 'start_lives')
    return JsonResponse(list(items), safe=False)


@require_GET
def campaign_detail(request, campaign_id: int):
    c = get_object_or_404(Campaign, pk=campaign_id)
    # Common lists
    towers = [
        {
            "id": t.id,
            "name": t.name,
            "cost": t.cost,
            "damage": t.damage,
            "range": t.range,
            "fireRate": t.fire_rate,
            "aoeAdditionalTargets": t.area_additional_targets,
            "aoeDamageRatio": t.area_damage_ratio,
            "aoeRange": t.area_range,
            "growth": {
                "cost": t.growth_cost_mult,
                "damage": t.growth_damage_mult,
                "range": t.growth_range_mult,
                "fireRate": t.growth_fire_rate_mult,
            },
            "iconShape": t.icon_shape,
            "iconColor": t.icon_color,
            "iconBlinkColor": t.icon_blink_color,
            "beamColor": t.beam_color,
            "beamWidth": t.beam_width,
            "beamDash": t.beam_dash,
        }
        for t in TowerType.objects.all()
    ]
    enemies = [
        {
            "id": e.id,
            "name": e.name,
            "hp": e.max_health,
            "speed": e.speed,
            "bounty": e.bounty,
            "iconShape": e.icon_shape,
            "iconColor": e.icon_color,
            "iconHitColor": e.icon_hit_color,
        }
        for e in EnemyType.objects.all()
    ]

    stages_payload = []
    for st in c.stages.all().order_by('order_index'):
        m = st.map
        path = list(PathNode.objects.filter(map=m).order_by('order_index').values('x', 'y'))
        build_spots = list(BuildSpot.objects.filter(map=m).values('x', 'y'))

        # Stage waves: use custom if available, else derive from Map if requested
        swaves = []
        s_custom = list(st.waves.all().order_by('wave_number'))
        if s_custom:
            for w in s_custom:
                groups = []
                for g in w.groups.all().order_by('order_index'):
                    groups.append({
                        "typeId": g.enemy_type_id,
                        "count": g.count,
                        "spawnInterval": g.spawn_interval,
                        "startDelay": g.start_delay,
                    })
                swaves.append({
                    "number": w.wave_number,
                    "groups": groups,
                })
        elif st.use_map_waves:
            qs = Wave.objects.filter(map=m).order_by('wave_number')
            if st.waves_to_play > 0:
                qs = qs[: st.waves_to_play]
            for w in qs:
                enemies_def = [
                    {
                        "typeId": we.enemy_type_id,
                        "count": we.count,
                        "spawnInterval": we.spawn_interval,
                        "startDelay": 0.0,
                    }
                    for we in WaveEnemy.objects.filter(wave=w)
                ]
                swaves.append({"number": w.wave_number, "groups": enemies_def})

        stages_payload.append({
            "map": {
                "id": m.id,
                "name": m.name,
                "width": m.width_tiles,
                "height": m.height_tiles,
                "path": path,
                "buildSpots": build_spots,
            },
            "message": st.message,
            "startMoneyOverride": st.start_money_override,
            "startLivesOverride": st.start_lives_override,
            "waves": swaves,
        })

    payload = {
        "id": c.id,
        "name": c.name,
        "startMoney": c.start_money,
        "startLives": c.start_lives,
        "towerTypes": towers,
        "enemyTypes": enemies,
        "stages": stages_payload,
    }
    return JsonResponse(payload)


@require_http_methods(["POST"])
@login_required
def create_campaign(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON payload')

    name = data.get('name') or 'New Campaign'
    start_money = int(data.get('startMoney') or 200)
    start_lives = int(data.get('startLives') or 20)
    stages = data.get('stages') or []

    camp = Campaign.objects.create(name=name, start_money=start_money, start_lives=start_lives)

    for i, st in enumerate(stages, start=1):
        m = get_object_or_404(Map, pk=int(st.get('mapId')))
        stage = CampaignStage.objects.create(
            campaign=camp,
            order_index=i,
            map=m,
            use_map_waves=bool(st.get('useMapWaves', False)),
            waves_to_play=int(st.get('wavesToPlay') or 0),
            message=st.get('message', '') or '',
            start_money_override=st.get('startMoneyOverride'),
            start_lives_override=st.get('startLivesOverride'),
        )
        custom = st.get('waves') or []
        for w in custom:
            sw = StageWave.objects.create(stage=stage, wave_number=int(w.get('number') or 1))
            for gi, g in enumerate(w.get('groups') or [], start=1):
                StageWaveGroup.objects.create(
                    wave=sw,
                    order_index=gi,
                    enemy_type=get_object_or_404(EnemyType, pk=int(g.get('typeId'))),
                    count=int(g.get('count') or 1),
                    spawn_interval=float(g.get('spawnInterval') or 1.0),
                    start_delay=float(g.get('startDelay') or 0.0),
                )

    return JsonResponse({"id": camp.id, "name": camp.name})


@require_http_methods(["PUT", "PATCH"])
@login_required
def update_campaign(request, campaign_id: int):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON payload')

    camp = get_object_or_404(Campaign, pk=campaign_id)
    camp.name = data.get('name') or camp.name
    if 'startMoney' in data:
        camp.start_money = int(data.get('startMoney') or camp.start_money)
    if 'startLives' in data:
        camp.start_lives = int(data.get('startLives') or camp.start_lives)
    camp.save()

    # Replace stages for simplicity
    camp.stages.all().delete()
    stages = data.get('stages') or []
    for i, st in enumerate(stages, start=1):
        m = get_object_or_404(Map, pk=int(st.get('mapId')))
        stage = CampaignStage.objects.create(
            campaign=camp,
            order_index=i,
            map=m,
            use_map_waves=bool(st.get('useMapWaves', False)),
            waves_to_play=int(st.get('wavesToPlay') or 0),
            message=st.get('message', '') or '',
            start_money_override=st.get('startMoneyOverride'),
            start_lives_override=st.get('startLivesOverride'),
        )
        for w in st.get('waves') or []:
            sw = StageWave.objects.create(stage=stage, wave_number=int(w.get('number') or 1))
            for gi, g in enumerate(w.get('groups') or [], start=1):
                StageWaveGroup.objects.create(
                    wave=sw,
                    order_index=gi,
                    enemy_type=get_object_or_404(EnemyType, pk=int(g.get('typeId'))),
                    count=int(g.get('count') or 1),
                    spawn_interval=float(g.get('spawnInterval') or 1.0),
                    start_delay=float(g.get('startDelay') or 0.0),
                )

    return JsonResponse({"id": camp.id, "name": camp.name})


@require_http_methods(["PUT", "PATCH"]) 
@login_required
def update_map(request, map_id: int):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON payload')

    m = get_object_or_404(Map, pk=map_id)
    if 'name' in data: m.name = data.get('name') or m.name
    if 'width' in data: m.width_tiles = int(data.get('width') or m.width_tiles)
    if 'height' in data: m.height_tiles = int(data.get('height') or m.height_tiles)
    m.save()

    # Replace nodes/spots
    PathNode.objects.filter(map=m).delete()
    BuildSpot.objects.filter(map=m).delete()
    pn = [PathNode(map=m, order_index=i, x=int(n['x']), y=int(n['y'])) for i, n in enumerate(data.get('path') or [])]
    if pn:
        PathNode.objects.bulk_create(pn)
    bs = [BuildSpot(map=m, x=int(s['x']), y=int(s['y'])) for s in (data.get('buildSpots') or [])]
    if bs:
        BuildSpot.objects.bulk_create(bs)

    return JsonResponse({"id": m.id, "name": m.name})


@require_http_methods(["POST"])
@login_required
def create_map(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON payload')

    name = data.get('name') or 'New Map'
    width = int(data.get('width') or 30)
    height = int(data.get('height') or 20)
    path = data.get('path') or []
    build_spots = data.get('buildSpots') or []

    if width <= 0 or height <= 0:
        return HttpResponseBadRequest('Width/height must be positive')

    m = Map.objects.create(name=name, width_tiles=width, height_tiles=height)
    # Path order is as provided
    pn = [PathNode(map=m, order_index=i, x=int(n['x']), y=int(n['y'])) for i, n in enumerate(path)]
    if pn:
        PathNode.objects.bulk_create(pn)
    bs = [BuildSpot(map=m, x=int(s['x']), y=int(s['y'])) for s in build_spots]
    if bs:
        BuildSpot.objects.bulk_create(bs)

    return JsonResponse({"id": m.id, "name": m.name})
