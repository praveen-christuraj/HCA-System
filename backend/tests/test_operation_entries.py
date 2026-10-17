"""OTMS payload/quantity parity and entry integration/security regressions."""
import csv
import io
import json
import math
import subprocess
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import JSON
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from app.database import SessionLocal, Base
from app.models import (Asset, OperationEntry, Table11Factor, AuditLog, OperationPosting, OperationEntryMultiTank,
    OperationEntryMultiTankStage, OperationEntryMultiTankDip, OperationEntryMultiTankSeal)
from app.services import quantity_engine as qe
from app.services.table11 import lookup_table11_factor
from app.utils.operation_entry_payloads import entry_definition_catalog


def tag(prefix): return f"{prefix}-{uuid.uuid4().hex[:8]}"


def post(client, headers, path, body, status=201):
    r = client.post(path, json=body, headers=headers)
    assert r.status_code == status, r.text
    return r.json()


def location(client, headers):
    code = tag('LOC')
    return post(client, headers, '/api/locations', {'location_code': code, 'location_name': code, 'location_type': 'Terminal'})


@pytest.fixture(autouse=True)
def empty_table11(client):
    with SessionLocal() as db:
        db.query(Table11Factor).delete(); db.commit()


def quality():
    return dict(tankTemperatureUnit='C', tankTemperature=25, observedInputType='Observed API', observedApi=35,
        observedDensity=None, sampleTemperatureUnit='F', sampleTemperature=77, bswPercent=1, remarks='Measured')


@pytest.fixture
def make_case(client, admin_headers):
    def make(kind='TANK_OPERATIONS', category='OPENING_STOCK', scope='Local', loc=None, chart=True):
        loc = loc or location(client, admin_headers)
        d = next(x for x in entry_definition_catalog() if x['operation_type_code'] == kind)
        tanks = ['1P','1S'] if kind == 'BARGE_OPERATIONS' else ['C1','C2'] if kind == 'TANKER_OPERATIONS' else ['MAIN'] if kind != 'FLOWMETER_OPERATIONS' else []
        asset = post(client, admin_headers, '/api/assets', dict(asset_name=tag('Asset'), asset_code=tag('A'), asset_type_code=d['asset_type_code'], asset_scope=scope,
            location_id=loc['id'] if scope == 'Local' else None, calibration_required=bool(tanks), tanks=[{'tank_name': t} for t in tanks]))
        op = post(client, admin_headers, '/api/operations', dict(location_id=loc['id'], operation_type_code=kind, operation_category=category,
            operation_code=tag('OP'), operation_label=tag('Operation')))
        if tanks and chart:
            content = 'tank_name,dip_ullage,volume\n' + ''.join(f'{t},{x},{v}\n' for t in tanks for x,v in [(0,0),(100,1000),(200,2500)])
            r=client.post(f"/api/assets/{asset['id']}/calibration/upload", headers=admin_headers, files={'file': ('chart.csv',content,'text/csv')},
                data={'chart_name':'Measured chart', 'measurement_basis':'Dip','dip_unit':'cm','volume_unit':'bbl','confirm':'true'})
            assert r.status_code == 200, r.text
        code=d['payload_field_code']
        if code=='tank_gauging_payload':
            p={'inputs': {**quality(), 'tankOperationCode':op['operation_code'], 'gaugingDate':'2026-10-17','gaugingTime':'08:30','dipCm':100,'waterLevelCm':10}}
        elif code=='tanker_payload':
            p={'inputs':{**quality(),'tankerTransactionDate':'2026-10-17','tankerTransactionTime':'08:30','compartment':'C1','totalDipCm':100,'waterDipCm':10,
                'operation':'Loading','sealC1':'C-1','sealC2':'C-2','sealM1':'M-1','sealM2':'M-2'}}
        elif code=='multi_tank_payload':
            stage=dict(date='2026-10-17',time='08:30',ccf=1.01,obsMode='Observed API',obsApi=35,obsDensity=None,sampleTempUnit='°F',sampleTemp=77,tankTempUnit='°C',tankTemp=25,bswPct=1)
            p={'meta': {'tankIds': tanks},'inputs': {'before':{**stage,'dips':{t:{'total':100,'water':10} for t in tanks}},'after':{**stage,'dips':{t:{'total':150,'water':10} for t in tanks}}},
                'seals': {'after': {'tankSeals': {}, 'temporary': {'portManifoldSeal':'P1','stbdManifoldSeal':'S1','pumproomSeal':'PM1','otherSeal':'O1','otherRemarks':'Inspection note'}}}}
        elif code in ('shuttle_payload','fso_payload'):
            p={'inputs':dict(event_time='08:30',opening_stock_bbl=100,opening_water_bbl=10,closing_stock_bbl=150,closing_water_bbl=12,remarks='Measured')}
            if code=='shuttle_payload': p['inputs']['barge_reference']='BRG-REF'
            else: p['inputs'].update(shuttle_number=tag('SH'),vessel_name='Vessel Alpha',vessel_quantity_bbl=60)
        else:
            cfg=post(client, admin_headers, '/api/operation-references/meters',dict(location_id=loc['id'],asset_id=asset['id'],stream_name=asset['asset_code'],meter_label='Meter A',meter_factor=1.002,meter_unit='m3'))
            p={'inputs':dict(stream_name=asset['asset_code'],reading_date='2026-10-17',event_time='08:30',tank_temperature_unit='C',tank_temperature=25,
                observed_input_type='Observed API',observed_api=35,observed_density=None,sample_temperature_unit='F',sample_temperature=77,bsw_percent=1,
                meters=[dict(config_id=cfg['id'],meter_label='Meter A',opening_reading=1000,closing_reading=2000,meter_factor=999,meter_unit='bbls')])}
        body=dict(operation_type_code=kind,payload_code=code,operation_id=op['id'],asset_id=asset['id'],location_id=loc['id'],operation_date='2026-10-17',
            convoy_number=tag('VOY'),product_name='Crude Oil',payload=p)
        if kind=='BARGE_OPERATIONS': body['barge_event_type']='LOAD_1'
        return {'body':body,'asset':asset,'op':op,'loc':loc,'definition':d}
    return make


def create(client,headers,case): return post(client,headers,'/api/operation-entries',case['body'])


def transition(client,headers,ticket,action,**kw):
    return post(client,headers,f"/api/operation-entries/{ticket['id']}/{action}",dict(version=ticket['version'],review_confirmed=True,remarks='Reviewed',**kw),status=200)


def person(client,admin_headers,perms,locations):
    role=post(client,admin_headers,'/api/roles',{'role_name':tag('Entry role')})
    cats=client.get('/api/permissions/catalog',headers=admin_headers).json()['categories']
    ids=[p['id'] for c in cats for m in c['modules'] for p in m['permissions'] if p['permission_name'] in perms]
    assert len(ids)==len(perms)
    assert client.put(f"/api/roles/{role['id']}/permissions",json={'permission_ids':ids},headers=admin_headers).status_code==200
    assert client.put(f"/api/role-locations/{role['id']}",json={'location_ids':locations},headers=admin_headers).status_code==200
    username=tag('entry-user')
    user=post(client,admin_headers,'/api/users',dict(username=username,full_name=username,email=username+'@example.com',password='Operator@12345',role_ids=[role['id']],force_password_change=False))
    login=client.post('/api/auth/login',json={'username':username,'password':'Operator@12345'}).json()
    return {'Authorization':'Bearer '+login['access_token']},role,user


def test_catalogue_fixed_and_all_asset_types(client,admin_headers):
    r=client.get('/api/operation-entries/options',headers=admin_headers)
    assert r.status_code==200
    definitions=r.json()['entry_definitions']
    assert len(definitions)==6
    assert {d['asset_type_code'] for d in definitions}=={'STORAGE_TANK','BARGE','SHUTTLE_VESSEL','FSO','TANKER_TRAILER','FLOWMETER'}
    assert sum(len(d['alternatives']) for d in definitions)==2
    assert not any('operation-templates' in getattr(r,'path','') for r in __import__('app.main',fromlist=['app']).app.routes)


def test_table11_is_never_fabricated():
    with pytest.raises(ValueError,match='empty'): lookup_table11_factor(35)
    rows=[(30,.14),(40,.13)] # Synthetic test reference, not a certified dataset.
    assert lookup_table11_factor(30,rows=rows)['lookup_method']=='Exact match'
    assert lookup_table11_factor(35,rows=rows)['lt_factor']==pytest.approx(.135)
    assert lookup_table11_factor(29,rows=rows)['lookup_method']=='Below range - nearest factor used'
    assert lookup_table11_factor(41,rows=rows)['lookup_method']=='Above range - nearest factor used'
    for v in (float('nan'),float('inf'),None):
        with pytest.raises(ValueError): lookup_table11_factor(v,rows=rows)


def test_js_math_round_and_temperature_parity():
    assert qe.js_round(-1.5)==-1
    assert qe.js_round(2.5)==3
    assert qe.api_observed_to_api60(35,77)==33.714
    assert qe.calculate_vcf(33.714,77)==.99206
    assert qe.api_observed_to_api60(35,77,decimals=2)==33.71
    # Execute the ported original OTMS JS engine, not a second Python implementation.
    root=Path(__file__).resolve().parents[2]
    code="""import {calculateTankQuantity} from './frontend/src/utils/tankQuantityEngine.js';
console.log(JSON.stringify(calculateTankQuantity({dipCm:100,waterLevelCm:10,tankTemperature:25,tankTemperatureUnit:'C',observedInputType:'Observed API',observedApi:35,sampleTemperature:77,sampleTemperatureUnit:'F',bswPercent:1,calibrationRows:[{dip:0,volume:0},{dip:100,volume:1000},{dip:200,volume:2500}],inputColumnName:'dip',outputColumnName:'volume'})));"""
    try: js=json.loads(subprocess.check_output(['node','--input-type=module','-e',code],cwd=root))
    except FileNotFoundError: pytest.skip('Node is required for cross-runtime formula parity')
    py=qe.calculate_tank_quantity(dip_cm=100,water_level_cm=10,tank_temperature=25,tank_temperature_unit='C',observed_input_type='Observed API',observed_api=35,
        sample_temperature=77,sample_temperature_unit='F',bsw_percent=1,calibration_points=[(0,0),(100,1000),(200,2500)])['calculated']
    for key in ['tovBbl','freeWaterBbl','govBbl','api60','density15','vcf','gsvBbl','bswBbl','nsvBbl','lt','mt']:
        assert py[key]==pytest.approx(js[key]),key


@pytest.mark.parametrize('kind',[d['operation_type_code'] for d in entry_definition_catalog()])
def test_every_payload_create_calculate_edit_roundtrip(client,admin_headers,make_case,kind):
    case=make_case(kind)
    t=create(client,admin_headers,case)
    assert t['status']=='Draft' and t['version']==1
    assert t['created_by']=='admin'
    p=t['payload']
    if kind=='TANK_OPERATIONS': assert p['calculated']['tovBbl']==1000
    if kind=='BARGE_OPERATIONS':
        assert p['calculated']['before']['TOV']==2020 # CCF applied before sum.
        assert p['calculated']['before']['API60']==33.71
        assert p['perTank']['before']['1P']['tovCorrected']==1010
        assert p['inputs']['before']['date']=='2026-10-17'
        assert p['seals']['after']['temporary']['otherRemarks']=='Inspection note'
        assert p['calculated']['before']['LT']==0 # No Table 11, exactly as OTMS.
    if kind=='SHUTTLE_OPERATIONS': assert p['calculated']['net']=={'net_stock_bbl':50,'net_water_bbl':2,'TOV':50,'FW':2,'NSV':50}
    if kind=='FSO_OPERATIONS': assert p['calculated']['net']['variance_bbl']==8
    if kind=='FLOWMETER_OPERATIONS':
        assert p['inputs']['meters'][0]['meter_factor']==1.002 # Never client-trusted 999.
        assert p['inputs']['meters'][0]['config_id']
        assert p['calculated']['stream_gross_observed']==1002
        assert p['calculated']['stream_gross_observed_bbl']==pytest.approx(1002*6.289811)
    if kind=='TANKER_OPERATIONS':
        assert p['calculated']['tovBbl']==1000 # canonical bbl, no double litres conversion
        assert p['inputs']['operation']=='Loading'
        assert p['inputs']['sealM2']=='M-2'
    # Simulate reopening/updating the full original payload; nested child keys stay stable.
    r=client.put(f"/api/operation-entries/{t['id']}",headers=admin_headers,json={'version':t['version'],'payload':p,'remarks':'Edited'})
    assert r.status_code==200,r.text
    assert r.json()['version']>t['version']
    assert r.json()['payload']==p
    t=r.json()
    t=transition(client,admin_headers,t,'submit')
    t=transition(client,admin_headers,t,'approve')
    assert t['status']=='Approved'
    with SessionLocal() as db: assert db.query(OperationPosting).filter_by(entry_id=t['id']).count()==1
    assert client.put(f"/api/operation-entries/{t['id']}",json={'version':t['version'],'remarks':'No'},headers=admin_headers).status_code==400
    assert client.post(f"/api/operation-entries/{t['id']}/approve",json={'version':t['version'],'review_confirmed':True},headers=admin_headers).status_code==400


@pytest.mark.parametrize('code,kind,inputs,expected',[
    ('stock_movement','FSO_OPERATIONS',dict(opening_stock=100,opening_water=5,closing_stock=250,closing_water=9),{'net_stock':150,'net_water':4,'net_nsv':146}),
    ('vessel_cycle','SHUTTLE_OPERATIONS',dict(quantity_bbl=250,water_bbl=7),{'nsv_bbl':243}),
])
def test_fixed_manual_layouts(client,admin_headers,make_case,code,kind,inputs,expected):
    c=make_case(kind);c['body'].update(payload_code=code,payload={'inputs':inputs})
    t=create(client,admin_headers,c)
    assert t['payload']['calculated']==expected


def test_table11_reference_mass_path_and_history_snapshot(client,admin_headers,make_case):
    for a,f in [(30,.14),(40,.13)]: post(client,admin_headers,'/api/operation-references/table11',dict(api60=a,lt_factor=f))
    c=make_case(); t=create(client,admin_headers,c)
    calc=t['payload']['calculated']
    assert calc['massMethod']=='Table 11 factor lookup'
    assert calc['table11LookupMethod']=='Linear interpolation'
    assert calc['ltFactor']==pytest.approx(.136286)
    # Replacing the chart/master cannot rewrite saved measurements or calibration identity.
    with SessionLocal() as db:
        asset=db.get(Asset,c['asset']['id']);asset.asset_name='Renamed';asset.calibration_table.chart_name='New Chart'
        db.query(Table11Factor).delete();db.commit()
    again=client.get(f"/api/operation-entries/{t['id']}",headers=admin_headers).json()
    assert again['payload']==t['payload']
    assert again['asset_name']==t['asset_name']


@pytest.mark.parametrize('updates,fragment',[
    ({'dipCm':300},'range'),({'dipCm':-1},'negative'),({'waterLevelCm':''},'required'),({'bswPercent':101},'BS&W'),
    ({'observedApi':999},'Observed API'),({'tankTemperature':80},'Tank Temperature'),({'gaugingDate':'bad'},'YYYY-MM-DD'),
    ({'gaugingTime':'25:00'},'HH:MM'),({'tankTemperatureUnit':'K'},'must be C or F'),
])
def test_server_validates_custody_inputs(client,admin_headers,make_case,updates,fragment):
    c=make_case();c['body']['payload']['inputs'].update(updates)
    r=client.post('/api/operation-entries',headers=admin_headers,json=c['body'])
    assert r.status_code==400,r.text
    assert fragment.lower() in r.text.lower()


def test_no_calibration_or_unknown_compartment_cannot_silently_zero(client,admin_headers,make_case):
    c=make_case(chart=False)
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==400
    c=make_case('TANKER_OPERATIONS');c['body']['payload']['inputs']['compartment']='not-C1'
    r=client.post('/api/operation-entries',headers=admin_headers,json=c['body'])
    assert r.status_code==400 and 'never substituted' in r.text


def test_payload_calculated_is_never_trusted(client,admin_headers,make_case):
    c=make_case();c['body']['payload']['calculated']={'tovBbl':999999,'nsvBbl':999999}
    assert create(client,admin_headers,c)['payload']['calculated']['tovBbl']==1000
    c['body']['status']='Approved'
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==422


def test_review_confirmation_and_optimistic_lock(client,admin_headers,make_case):
    t=create(client,admin_headers,make_case())
    assert client.post(f"/api/operation-entries/{t['id']}/submit",json={'version':t['version']},headers=admin_headers).status_code==400
    r=client.put(f"/api/operation-entries/{t['id']}",json={'version':t['version'],'remarks':'first'},headers=admin_headers)
    assert r.status_code==200
    stale=client.put(f"/api/operation-entries/{t['id']}",json={'version':t['version'],'remarks':'stale'},headers=admin_headers)
    assert stale.status_code==409
    stale_submit=client.post(f"/api/operation-entries/{t['id']}/submit",json={'version':t['version'],'review_confirmed':True},headers=admin_headers)
    assert stale_submit.status_code==409


def test_state_machine_and_audit(client,admin_headers,make_case):
    t=create(client,admin_headers,make_case())
    for action in ('submit','recall','submit','reject','submit','recall','cancel'):
        t=transition(client,admin_headers,t,action)
    detail=client.get(f"/api/operation-entries/{t['id']}",headers=admin_headers).json()
    assert [h['action'] for h in detail['status_history']]==['Create','Submit','Recall','Submit','Reject','Submit','Recall','Cancel']
    assert detail['status']=='Cancelled'
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(module_name='Operation Entry',entity_id=t['id'],action='Cancel').count()==1
        assert db.query(OperationEntry).filter_by(id=t['id']).count()==1


def test_multi_tank_master_seals_cannot_be_forged(client,admin_headers,make_case):
    c=make_case('BARGE_OPERATIONS')
    tank=c['asset']['tanks'][0]
    post(client,admin_headers,'/api/operation-references/seals',dict(asset_id=c['asset']['id'],tank_id=tank['id'],seal_position='MH1',seal_number='CERT-1'))
    p=c['body']['payload'];p['seals']['after']['tankSeals']={tank['tank_name']:{'MH1':{'master':'forged','observed':'BROKEN'}}}
    t=create(client,admin_headers,c)
    assert t['payload']['seals']['after']['tankSeals'][tank['tank_name']]['MH1']['master']=='CERT-1'
    r=client.post(f"/api/operation-entries/{t['id']}/submit",json={'version':t['version'],'review_confirmed':True},headers=admin_headers)
    assert r.status_code==400 and 'mismatch' in r.text
    t=transition(client,admin_headers,t,'submit')
    assert t['status']=='Submitted'


def test_multi_tank_missing_temp_seal_blocks_submit(client,admin_headers,make_case):
    c=make_case('BARGE_OPERATIONS');c['body']['payload']['seals']['after']['temporary']['portManifoldSeal']=''
    t=create(client,admin_headers,c)
    r=client.post(f"/api/operation-entries/{t['id']}/submit",json={'version':t['version'],'review_confirmed':True},headers=admin_headers)
    assert r.status_code==400 and 'portManifoldSeal' in r.text


def test_rbac_creation_edit_review_submission_are_independent(client,admin_headers,make_case):
    c=make_case()
    creator,_,_=person(client,admin_headers,['operation_entries:read','operation_entries:create','operation_entries:update'],[c['loc']['id']])
    t=create(client,creator,c)
    assert client.post(f"/api/operation-entries/{t['id']}/submit",headers=creator,json={'version':t['version'],'review_confirmed':True}).status_code==403
    submitter,_,_=person(client,admin_headers,['operation_entries:read','operation_submissions:create'],[c['loc']['id']])
    assert client.post(f"/api/operation-entries/{t['id']}/submit",headers=submitter,json={'version':t['version'],'review_confirmed':True}).status_code==403
    reviewed,_,_=person(client,admin_headers,['operation_entries:read','operation_submissions:create','operation_reviews:create'],[c['loc']['id']])
    assert transition(client,reviewed,t,'submit')['status']=='Submitted'
    assert client.post('/api/operation-entries',headers=reviewed,json=c['body']).status_code==403


def test_entry_lookups_do_not_need_master_admin_permissions(client,admin_headers,make_case):
    c=make_case()
    user,_,_=person(client,admin_headers,['operation_entries:read','operation_entries:create'],[c['loc']['id']])
    assert client.get('/api/assets',headers=user).status_code==403
    assert client.get('/api/operation-entries/lookups/assets',headers=user).status_code==200
    assert client.get(f"/api/operation-entries/asset-context/{c['asset']['id']}",headers=user).status_code==200
    assert client.get('/api/operation-references/meters',headers=user).status_code==200
    assert client.post('/api/operation-references/table11',headers=user,json={'api60':40,'lt_factor':.1}).status_code==403


def test_scoping_covers_calculate_context_export_dashboard(client,admin_headers,make_case):
    own=make_case();far=make_case()
    create(client,admin_headers,far)
    user,_,_=person(client,admin_headers,['operation_entries:read','operation_entries:create'],[own['loc']['id']])
    assert client.get(f"/api/operation-entries/asset-context/{far['asset']['id']}",headers=user).status_code==403
    calc={k:far['body'][k] for k in ('operation_type_code','payload_code','asset_id','location_id','payload')}
    assert client.post('/api/operation-entries/calculate',headers=user,json=calc).status_code==403
    assert far['asset']['asset_code'] not in client.get('/api/operation-entries/export?format=csv',headers=user).text
    dash=client.get('/api/dashboard/modules/business',headers=user)
    assert dash.status_code==200,dash.text
    assert next(k['value'] for k in dash.json()['kpis'] if k['label']=='Operation entries')==0
    # Same code at another terminal must not satisfy Operation Master availability.
    own['body']['operation_id']=far['op']['id']
    assert client.post('/api/operation-entries',headers=user,json=own['body']).status_code==400


def test_workflow_policy_role_user_override(client,admin_headers,make_case):
    c=make_case()
    user,role,u=person(client,admin_headers,['operation_entries:read','operation_entries:create'],[c['loc']['id']])
    policy=post(client,admin_headers,'/api/operation-references/policies',dict(policy_name=tag('POL'),action_code='CREATE_ENTRY',location_id=c['loc']['id'],operation_type_code='TANK_OPERATIONS',role_ids=[],allow_user_ids=[],deny_user_ids=[]))
    assert client.post('/api/operation-entries',headers=user,json=c['body']).status_code==403
    body=dict(policy_name=policy['policy_name'],action_code='CREATE_ENTRY',location_id=c['loc']['id'],operation_type_code='TANK_OPERATIONS',role_ids=[role['id']],allow_user_ids=[],deny_user_ids=[])
    assert client.put(f"/api/operation-references/policies/{policy['id']}",headers=admin_headers,json=body).status_code==200
    assert create(client,user,c)['status']=='Draft'
    body['deny_user_ids']=[u['id']]
    assert client.put(f"/api/operation-references/policies/{policy['id']}",headers=admin_headers,json=body).status_code==200
    assert client.post('/api/operation-entries',headers=user,json=c['body']).status_code==403


def test_receiver_cross_location_and_unique_sender_link(client,admin_headers,make_case):
    c=make_case('TANKER_OPERATIONS',category='DISPATCH',scope='Global')
    dest=location(client,admin_headers)
    c['body'].update(receiver_location_id=dest['id'],destination_location_id=dest['id'])
    sender=create(client,admin_headers,c);sender=transition(client,admin_headers,sender,'submit');sender=transition(client,admin_headers,sender,'approve')
    op=post(client,admin_headers,'/api/operations',dict(location_id=dest['id'],operation_type_code='TANKER_OPERATIONS',operation_category='RECEIPT',operation_code=tag('REC'),operation_label=tag('Receipt')))
    user,_,_=person(client,admin_headers,['operation_entries:read','receiving_tickets:create'],[dest['id']])
    assert client.get(f"/api/operation-entries/linked-sender/{sender['id']}",headers=user).status_code==200
    body=deepcopy(c['body']);body.update(operation_id=op['id'],location_id=dest['id'],sender_location_id=c['loc']['id'],linked_ticket_id=sender['id'])
    receiver=post(client,user,'/api/operation-entries',body)
    assert receiver['payload']['sender_reference']['sender_transaction_id']==sender['id']
    assert client.post('/api/operation-entries',headers=user,json=body).status_code==409
    body['convoy_number']='FORGED'
    assert client.post('/api/operation-entries',headers=user,json=body).status_code in (400,409)
    body.pop('linked_ticket_id')
    assert client.post('/api/operation-entries',headers=user,json=body).status_code==403
    stranger,_,_=person(client,admin_headers,['operation_entries:read'],[location(client,admin_headers)['id']])
    assert client.get(f"/api/operation-entries/{sender['id']}",headers=stranger).status_code==404


def test_shuttle_uniqueness_closed_voyage_fso_reference(client,admin_headers,make_case):
    c=make_case('SHUTTLE_OPERATIONS',category='DISPATCH')
    client.put(f"/api/operations/{c['op']['id']}",headers=admin_headers,json={'operation_label':'UNLOAD TO FSO '+tag('OUT')})
    t=create(client,admin_headers,c)
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==400
    voyages=client.get('/api/operation-references/voyages',params={'search':t['convoy_number']},headers=admin_headers).json()['items']
    v=voyages[0]
    assert client.put(f"/api/operation-references/voyages/{v['id']}",headers=admin_headers,json={'status':'CLOSED','closure_remarks':'done'}).status_code==400
    t=transition(client,admin_headers,t,'submit');t=transition(client,admin_headers,t,'approve')
    assert client.put(f"/api/operation-references/voyages/{v['id']}",headers=admin_headers,json={'status':'CLOSED','closure_remarks':'done'}).status_code==200
    ref=client.get('/api/operation-entries/closed-shuttle',params={'shuttle_number':t['convoy_number']},headers=admin_headers)
    assert ref.status_code==200,ref.text
    assert ref.json()['rows'][0]['netDischargeBbl']==52


def test_meter_validation_and_canonical_calculated_rows(client,admin_headers,make_case):
    c=make_case('FLOWMETER_OPERATIONS');m=c['body']['payload']['inputs']['meters'][0]
    m['closing_reading']=m['opening_reading']-1
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==400
    m['closing_reading']=2000;m['config_id']=999999
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==400


def test_filters_exports_and_server_pagination(client,admin_headers,make_case):
    c=make_case();t=create(client,admin_headers,c)
    params={'search':t['ticket_number'],'status':'Draft','date_from':'2026-10-01','date_to':'2026-10-31','page_size':50}
    r=client.get('/api/operation-entries',params=params,headers=admin_headers).json()
    assert r['total']==1 and r['page_size']==50 and r['items'][0]['payload'] is None
    for format in ('csv','xlsx','pdf'):
        export=client.get('/api/operation-entries/export',params={**params,'format':format},headers=admin_headers)
        assert export.status_code==200,export.text
        if format=='pdf': assert export.content.startswith(b'%PDF')
    assert client.get('/api/operation-entries?date_from=2026-12-01&date_to=2026-01-01',headers=admin_headers).status_code==400


def _import_file(client,headers,code,rows,confirm=False,format='csv'):
    fields=list(rows[0])
    if format=='csv':
        buff=io.StringIO();w=csv.DictWriter(buff,fieldnames=fields);w.writeheader();w.writerows(rows);content=buff.getvalue().encode()
    else:
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active;ws.append(fields)
        for r in rows: ws.append([r.get(k) for k in fields])
        buff=io.BytesIO();wb.save(buff);content=buff.getvalue()
    return client.post('/api/operation-entry-import',headers=headers,files={'file':('entry.'+format,content)},data={'payload_code':code,'confirm':str(confirm).lower()})


@pytest.mark.parametrize('format',['csv','xlsx'])
def test_ticket_import_preview_atomic_commit(client,admin_headers,make_case,format):
    c=make_case();body=c['body'];row={k:body[k] for k in ('asset_id','location_id','operation_id','operation_date','product_name')}
    row.update({'input_'+k:v for k,v in body['payload']['inputs'].items() if k!='tankOperationCode'})
    row['ticket_key']='T1'
    preview=_import_file(client,admin_headers,body['payload_code'],[row],format=format)
    assert preview.status_code==200,preview.text
    assert preview.json()['invalid_rows']==0,preview.text
    committed=_import_file(client,admin_headers,body['payload_code'],[row],True,format)
    assert committed.status_code==200 and committed.json()['imported']==1,committed.text
    bad={**row,'ticket_key':'T2','input_dipCm':9999}
    before=client.get('/api/operation-entries',params={'asset_id':body['asset_id']},headers=admin_headers).json()['total']
    failed=_import_file(client,admin_headers,body['payload_code'],[row,bad],True,format)
    assert failed.status_code==400
    assert client.get('/api/operation-entries',params={'asset_id':body['asset_id']},headers=admin_headers).json()['total']==before


def test_no_json_storage_and_postgres_schema_compiles():
    for table in Base.metadata.tables.values():
        assert not any(isinstance(c.type,JSON) for c in table.columns),table.name
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize('payload',[
    {'inputs': []}, {'inputs': 'not-object'}, {'meta': 12},
    {'inputs': {'custom_quantity': 5}}, {'inputs': {'dipCm': {'override': 1}}},
])
def test_malformed_or_custom_payloads_are_400_not_500(client,admin_headers,make_case,payload):
    c=make_case();c['body']['payload']=payload
    r=client.post('/api/operation-entries',headers=admin_headers,json=c['body'])
    assert r.status_code==400,r.text


def test_blank_or_invalid_barge_stage_cannot_bypass_validation(client,admin_headers,make_case):
    c=make_case('BARGE_OPERATIONS');c['body']['payload']['inputs']['before']='bad'
    r=client.post('/api/operation-entries',headers=admin_headers,json=c['body'])
    assert r.status_code==400,r.text
    c=make_case('BARGE_OPERATIONS');c['body']['payload']['seals']['after']['tankSeals']={'1P':{'MH1':{'observed':[]}}}
    assert client.post('/api/operation-entries',headers=admin_headers,json=c['body']).status_code==400


def test_input_precision_is_not_silently_truncated(client,admin_headers,make_case):
    c=make_case();c['body']['payload']['inputs']['dipCm']='100.00001'
    r=client.post('/api/operation-entries',headers=admin_headers,json=c['body'])
    assert r.status_code==400 and 'decimal places' in r.text


def test_linked_receiving_local_asset_has_narrow_calibration_access(client,admin_headers,make_case):
    c=make_case('TANKER_OPERATIONS',category='DISPATCH',scope='Local')
    dest=location(client,admin_headers);c['body'].update(receiver_location_id=dest['id'],destination_location_id=dest['id'])
    sender=create(client,admin_headers,c);sender=transition(client,admin_headers,sender,'submit');sender=transition(client,admin_headers,sender,'approve')
    receiver,_,_=person(client,admin_headers,['operation_entries:read','receiving_tickets:create'],[dest['id']])
    path=f"/api/operation-entries/asset-context/{c['asset']['id']}"
    assert client.get(path,headers=receiver).status_code==403
    ctx=client.get(path,params={'linked_ticket_id':sender['id']},headers=receiver)
    assert ctx.status_code==200 and ctx.json()['chart']['rows'],ctx.text
    op=post(client,admin_headers,'/api/operations',dict(location_id=dest['id'],operation_type_code='TANKER_OPERATIONS',operation_category='RECEIPT',operation_code=tag('RECEIVE'),operation_label=tag('Receive')))
    body=deepcopy(c['body']);body.update(operation_id=op['id'],location_id=dest['id'],sender_location_id=c['loc']['id'],linked_ticket_id=sender['id'])
    assert post(client,receiver,'/api/operation-entries',body)['linked_ticket_id']==sender['id']


def test_shuttle_discharge_uses_absolute_product_and_water_separately(client,admin_headers,make_case):
    c=make_case('SHUTTLE_OPERATIONS',category='DISPATCH')
    client.put(f"/api/operations/{c['op']['id']}",headers=admin_headers,json={'operation_label':tag('UNLOADING')})
    c['body']['payload']['inputs'].update(closing_stock_bbl=50,closing_water_bbl=12)
    t=create(client,admin_headers,c);t=transition(client,admin_headers,t,'submit');t=transition(client,admin_headers,t,'approve')
    v=client.get('/api/operation-references/voyages',params={'search':t['convoy_number']},headers=admin_headers).json()['items'][0]
    client.put(f"/api/operation-references/voyages/{v['id']}",headers=admin_headers,json={'status':'CLOSED','closure_remarks':'Discharged'})
    r=client.get('/api/operation-entries/closed-shuttle',params={'shuttle_number':t['convoy_number']},headers=admin_headers)
    assert r.status_code==200,r.text
    assert r.json()['rows'][0]['netDischargeBbl']==52 # abs(-50) + abs(2), not abs(-48)


def test_sts_out_is_not_fso_discharge(client,admin_headers,make_case):
    c=make_case('SHUTTLE_OPERATIONS',category='ITT')
    client.put(f"/api/operations/{c['op']['id']}",headers=admin_headers,json={'operation_label':tag('STS OUT UNLOAD')})
    t=create(client,admin_headers,c);t=transition(client,admin_headers,t,'submit');t=transition(client,admin_headers,t,'approve')
    v=client.get('/api/operation-references/voyages',params={'search':t['convoy_number']},headers=admin_headers).json()['items'][0]
    client.put(f"/api/operation-references/voyages/{v['id']}",headers=admin_headers,json={'status':'CLOSED','closure_remarks':'Transfer complete'})
    r=client.get('/api/operation-entries/closed-shuttle',params={'shuttle_number':t['convoy_number']},headers=admin_headers)
    assert r.json()['rows'][0]['netDischargeBbl']==0


def test_export_full_snapshot_and_paginated_history(client,admin_headers,make_case):
    from app.models import OperationEntryStatusHistory
    t=create(client,admin_headers,make_case())
    with SessionLocal() as db:
        for i in range(30): db.add(OperationEntryStatusHistory(entry_id=t['id'],from_status='Draft',to_status='Draft',action='Historical note',remarks=str(i)))
        db.commit()
    detail=client.get(f"/api/operation-entries/{t['id']}",headers=admin_headers).json()
    assert len(detail['status_history'])==20 and detail['status_history_total']==31
    history=client.get(f"/api/operation-entries/{t['id']}/history?page=2&page_size=20",headers=admin_headers).json()
    assert history['total']==31 and len(history['items'])==11
    for fmt in ('csv','xlsx','pdf'):
        r=client.get(f"/api/operation-entries/{t['id']}/export?format={fmt}",headers=admin_headers)
        assert r.status_code==200,r.text
        if fmt=='csv': assert 'payload.inputs.dipCm' in r.text


@pytest.mark.parametrize('code,kind', [('multi_tank_payload','BARGE_OPERATIONS'),('flowmeter_payload','FLOWMETER_OPERATIONS')])
def test_grouped_fixed_imports(client,admin_headers,make_case,code,kind):
    from app.routers.operation_entry_import import headers_for
    c=make_case(kind);b=c['body'];rows=[]
    base={k:b.get(k,'') for k in ('operation_id','asset_id','location_id','operation_date','convoy_number')}
    base['ticket_key']='GROUP-1'
    if code=='multi_tank_payload':
        for tank in ['1P','1S']:
            row={**base,'tank_name':tank,'portManifoldSeal':'P1','stbdManifoldSeal':'S1','pumproomSeal':'PM1'}
            for stage in ['before','after']:
                for k,v in b['payload']['inputs'][stage].items():
                    if k!='dips':row[stage+'_'+k]=v
                row.update({stage+'_total':100 if stage=='before' else 150,stage+'_water':10})
            rows.append(row)
    else:
        inputs=b['payload']['inputs'];row={**base,**{'input_'+k:v for k,v in inputs.items() if k!='meters'}}
        row.update({k:inputs['meters'][0][k] for k in ('config_id','opening_reading','closing_reading')});rows=[row]
    r=_import_file(client,admin_headers,code,rows,True)
    assert r.status_code==200 and r.json()['imported']==1,r.text
    entries=client.get('/api/operation-entries',params={'asset_id':b['asset_id']},headers=admin_headers).json()['items']
    assert len(entries)==1
    t=client.get(f"/api/operation-entries/{entries[0]['id']}",headers=admin_headers).json()
    if code=='multi_tank_payload': assert set(t['payload']['perTank']['before'])=={'1P','1S'}
    else: assert t['payload']['inputs']['meters'][0]['meter_factor']==1.002


def test_reference_import_is_previewed_and_atomic(client,admin_headers):
    csvfile=b'api60,lt_factor\n30,0.14\n40,-1\n'
    preview=client.post('/api/operation-references/table11/import',headers=admin_headers,files={'file':('refs.csv',csvfile)},data={'confirm':'false'})
    assert preview.status_code==200 and preview.json()['invalid_rows']==1
    commit=client.post('/api/operation-references/table11/import',headers=admin_headers,files={'file':('refs.csv',csvfile)},data={'confirm':'true'})
    assert commit.status_code==400
    assert client.get('/api/operation-references/table11',headers=admin_headers).json()['total']==0


def test_mixed_timezone_header_comparison_is_normalized(client,admin_headers,make_case):
    c=make_case();c['body'].update(operation_start_datetime='2026-10-17T09:00:00+01:00',operation_end_datetime='2026-10-17T08:30:00')
    assert create(client,admin_headers,c)['operation_start_datetime']=='2026-10-17T08:00:00'


def test_alias_type_is_canonicalized_without_a_500(client,admin_headers,make_case):
    c=make_case();c['body']['operation_type_code']='Tank Operations'
    assert create(client,admin_headers,c)['operation_type_code']=='TANK_OPERATIONS'


GOLDEN = json.loads((Path(__file__).parent / 'fixtures' / 'otms_quantity_golden.json').read_text())


@pytest.mark.parametrize('case', GOLDEN['tank'])
def test_numerical_golden_from_original_otms_tank_source(case):
    x=case['input']
    r=qe.calculate_tank_quantity(dip_cm=x['dipCm'],water_level_cm=x['waterLevelCm'],tank_temperature=x['tankTemperature'],tank_temperature_unit=x['tankTemperatureUnit'],
        observed_input_type=x['observedInputType'],observed_api=x['observedApi'],observed_density=x['observedDensity'],sample_temperature=x['sampleTemperature'],sample_temperature_unit=x['sampleTemperatureUnit'],
        bsw_percent=x['bswPercent'],calibration_points=[(p['dip'],p['volume']) for p in x['calibrationRows']])['calculated']
    for k,v in case['expected'].items():
        assert r[k]==(pytest.approx(v,rel=1e-10,abs=1e-10) if isinstance(v,(int,float)) else v),k


@pytest.mark.parametrize('case', GOLDEN['multi'])
def test_numerical_golden_from_original_otms_multi_tank_source(case):
    with SessionLocal() as db:
        db.add(Table11Factor(api60=case['lookup']['api60'],lt_factor=case['lookup']['ltFactor']));db.commit()
        result=qe.compute_stage_totals(stage=case['input'],tank_ids=case['tankIds'],tank_curves={k:[(p['x'],p['y']) for p in points] for k,points in case['tankPoints'].items()},db=db)
        for k,v in case['expected']['totals'].items():
            assert result['totals'][k]==(pytest.approx(v,rel=1e-10,abs=1e-10) if isinstance(v,(int,float)) else v),k
        assert result['perTank']==case['expected']['perTank']
        assert result['totals']['table11']==case['lookup']


@pytest.mark.parametrize('case', GOLDEN['flow'])
def test_numerical_golden_from_original_otms_flowmeter_source(case):
    inputs=case['expected']['inputs']
    result=qe.calculate_flowmeter_quantities(inputs)
    for k,v in case['expected']['calculated'].items(): assert result['calculated'][k]==pytest.approx(v,rel=1e-10,abs=1e-10),k
    for actual,expected in zip(result['meters'],inputs['meters']):
        for k,v in expected.items(): assert actual[k]==(pytest.approx(v,rel=1e-10,abs=1e-10) if isinstance(v,(int,float)) else v),k


def test_ullage_basis_and_snapshot_are_explicit(client,admin_headers,make_case):
    c=make_case()
    content='tank_name,dip_ullage,volume\nMAIN,0,2500\nMAIN,100,1000\nMAIN,200,0\n'
    r=client.post(f"/api/assets/{c['asset']['id']}/calibration/upload",headers=admin_headers,files={'file':('ullage.csv',content)},data={
        'confirm':'true','chart_name':'Ullage chart','measurement_basis':'Ullage','dip_unit':'cm','volume_unit':'bbl'})
    assert r.status_code==200,r.text
    c['body']['payload']['inputs'].update(dipCm=100,waterLevelCm=150)
    t=create(client,admin_headers,c)
    assert t['payload']['calibration']['measurement_basis']=='Ullage'
    assert t['payload']['calculated']['tovBbl']==1000
    assert t['payload']['calculated']['freeWaterBbl']==500
    assert not any('Water Level is greater than Dip' in w for w in t['payload']['validation']['warnings'])


def test_native_excel_dates_and_times_import(client,admin_headers,make_case):
    from datetime import date, time
    c=make_case();b=c['body']
    row={k:b[k] for k in ('asset_id','operation_id','location_id')}
    row.update(ticket_key='NATIVE',operation_date=date(2026,10,17))
    row.update({'input_'+k:v for k,v in b['payload']['inputs'].items() if k!='tankOperationCode'})
    row['input_gaugingDate']=date(2026,10,17)
    row['input_gaugingTime']=time(8,30)
    r=_import_file(client,admin_headers,'tank_gauging_payload',[row],True,'xlsx')
    assert r.status_code==200 and r.json()['imported']==1,r.text


def test_adding_compartment_preserves_existing_calibration_and_seal_identity(client,admin_headers,make_case):
    c=make_case('BARGE_OPERATIONS');asset=c['asset']
    original={t['tank_name']:t['id'] for t in asset['tanks']}
    post(client,admin_headers,'/api/operation-references/seals',dict(asset_id=asset['id'],tank_id=original['1P'],seal_position='MH1',seal_number='P-MASTER'))
    r=client.put(f"/api/assets/{asset['id']}",headers=admin_headers,json={'tanks':[{'tank_name':'1P'},{'tank_name':'1S'},{'tank_name':'2P'}]})
    assert r.status_code==200,r.text
    assert {t['tank_name']:t['id'] for t in r.json()['tanks'] if t['tank_name'] in original}==original
    ctx=client.get(f"/api/operation-entries/asset-context/{asset['id']}",headers=admin_headers).json()
    assert len(ctx['chart']['rows'])==6
    assert ctx['seals'][0]['sealNumber']=='P-MASTER'
    blocked=client.put(f"/api/assets/{asset['id']}",headers=admin_headers,json={'tanks':[{'tank_name':'1S'},{'tank_name':'2P'}]})
    assert blocked.status_code==422 and 'Seal Master' in blocked.text
