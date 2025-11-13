import os, sys, django
sys.path.append(os.path.dirname(__file__) or '.')
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','STATZWeb.settings')
django.setup()
from td_now.models import Campaign, CampaignStage, StageWave, StageWaveGroup, Map, PathNode, BuildSpot

print('Campaigns:', Campaign.objects.count())
for c in Campaign.objects.all():
    print('Campaign', c.id, c.name, 'stages:', c.stages.count(), 'start', c.start_money, c.start_lives)
    for st in c.stages.order_by('order_index'):
        m = st.map
        print('  Stage', st.order_index, 'map', m.id, m.name, 'size', m.width_tiles, 'x', m.height_tiles)
        print('   path nodes:', PathNode.objects.filter(map=m).count(), 'build spots:', BuildSpot.objects.filter(map=m).count())
        swc = st.waves.count()
        print('   custom waves:', swc, 'use_map_waves:', st.use_map_waves)
        for w in st.waves.order_by('wave_number'):
            print('    Wave', w.wave_number, 'groups:', w.groups.count())
