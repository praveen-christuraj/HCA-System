import { test, expect } from '@playwright/test'

const types = {
  TANK_OPERATIONS: ['STORAGE_TANK', ['MAIN']], BARGE_OPERATIONS: ['BARGE', ['1P','1S']],
  TANKER_OPERATIONS: ['TANKER_TRAILER', ['C1','C2']], SHUTTLE_OPERATIONS: ['SHUTTLE_VESSEL',['MAIN']],
  FSO_OPERATIONS: ['FSO',['MAIN']], FLOWMETER_OPERATIONS: ['FLOWMETER',[]],
}
const tag = () => Math.random().toString(36).slice(2,10)
async function setup(page, request, theme) {
  if (!process.env.HCA_E2E_PASSWORD) throw new Error('Set HCA_E2E_PASSWORD for an isolated, seeded development database.')
  const r = await request.post('/api/auth/login', { data: { username: process.env.HCA_E2E_USERNAME || 'admin', password: process.env.HCA_E2E_PASSWORD } })
  expect(r.ok()).toBeTruthy()
  const login = await r.json()
  await page.addInitScript(({ login, theme }) => {
    localStorage.setItem('hca.accessToken',login.access_token);localStorage.setItem('hca.refreshToken',login.refresh_token);localStorage.setItem('hca.theme',theme)
  }, { login, theme })
  const headers = { Authorization: 'Bearer '+login.access_token }
  const post = async (url,data) => {
    const r=await request.post(url,{headers,data}); expect(r.ok(),await r.text()).toBeTruthy(); return r.json()
  }
  return { headers, post }
}
async function fixture(api, request, type) {
  const key=tag(), [assetType,tanks]=types[type]
  const loc=await api.post('/api/locations',{location_code:'E2E-'+key,location_name:'Entry terminal '+key,location_type:'Terminal'})
  const asset=await api.post('/api/assets',{asset_code:'E2E-A-'+key,asset_name:'Entry asset '+key,asset_type_code:assetType,asset_scope:'Local',location_id:loc.id,calibration_required:!!tanks.length,tanks:tanks.map(tank_name=>({tank_name}))})
  const op=await api.post('/api/operations',{location_id:loc.id,operation_type_code:type,operation_category:'OPENING_STOCK',operation_code:'E2E-OP-'+key,operation_label:'Opening '+key})
  if(tanks.length){
    const content='tank_name,dip_ullage,volume\n'+tanks.flatMap(t=>[`${t},0,0`,`${t},100,1000`,`${t},200,2500`]).join('\n')
    const r=await request.post(`/api/assets/${asset.id}/calibration/upload`,{headers:api.headers,multipart:{file:{name:'chart.csv',mimeType:'text/csv',buffer:Buffer.from(content)},confirm:'true',chart_name:'E2E chart',measurement_basis:'Dip',dip_unit:'cm',volume_unit:'bbl'}})
    expect(r.ok(),await r.text()).toBeTruthy()
  }
  if(type==='FLOWMETER_OPERATIONS') await api.post('/api/operation-references/meters',{asset_id:asset.id,location_id:loc.id,stream_name:asset.asset_code,meter_label:'Meter A',meter_factor:1.002,meter_unit:'m3'})
  return {loc,asset,op,key}
}
async function pick(page,label,code){
  const root=page.locator('.entry-header-grid .entry-lookup').filter({has:page.locator('label',{hasText:new RegExp('^'+label)})}).first()
  await root.locator('.entry-lookup-trigger').click()
  await root.locator('input').fill(code)
  await root.getByRole('option').filter({hasText:code}).first().click()
}
async function fillNamed(root, data){
  for(const [key,value] of Object.entries(data)) {
    const input=root.locator(`[name="${key}"]`)
    const details=input.locator('xpath=ancestor::details[1]')
    if(await details.count() && await details.getAttribute('open') === null) await details.locator('summary').click()
    if(await input.evaluate(e=>e.tagName)==='SELECT') await input.selectOption(String(value))
    else await input.fill(String(value))
  }
}
async function fillLayout(page,type,key){
  const layout=page.locator('.entry-layout-container')
  const q={ tankTemperatureUnit:'C',tankTemperature:25,observedInputType:'Observed API',observedApi:35,sampleTemperatureUnit:'F',sampleTemperature:77,bswPercent:1 }
  if(type==='TANK_OPERATIONS') await fillNamed(layout,{gaugingDate:'2026-10-17',gaugingTime:'08:30',dipCm:100,waterLevelCm:10,...q})
  else if(type==='TANKER_OPERATIONS') await fillNamed(layout,{tankerTransactionDate:'2026-10-17',tankerTransactionTime:'08:30',compartment:'C1',totalDipCm:100,waterDipCm:10,...q,sealC1:'C-1',sealC2:'C-2',sealM1:'M-1',sealM2:'M-2'})
  else if(type==='BARGE_OPERATIONS'){
    const stages=layout.locator('.multi-tank-grid > .multi-tank-card')
    for(let i=0;i<2;i++){
      const s=stages.nth(i)
      for(const [label,value] of Object.entries({Date:'2026-10-17',Time:'08:30',CCF:'1.01','BS&W (%)':'1','Obs API':'35','Sample Temp':'77','Tank Temp':'25'})) await s.getByLabel(label,{exact:true}).fill(value)
      await s.getByLabel('Sample Unit',{exact:true}).selectOption('°F')
      await s.getByLabel('Tank Unit',{exact:true}).selectOption('°C')
      const rows=s.locator('tbody tr')
      for(let j=0;j<2;j++){
        await rows.nth(j).locator('input').nth(0).fill(i ? '150' : '100')
        await rows.nth(j).locator('input').nth(1).fill('10')
      }
    }
    await layout.getByRole('button',{name:'Show Seals',exact:true}).click()
    await layout.getByLabel('Port Manifold Seal',{exact:true}).fill('P1')
    await layout.getByLabel('Starboard Manifold Seal',{exact:true}).fill('S1')
    await layout.getByLabel('Pumproom Seal',{exact:true}).fill('PM1')
  } else if(type==='FLOWMETER_OPERATIONS'){
    await fillNamed(layout,{reading_date:'2026-10-17',event_time:'08:30',tank_temperature_unit:'C',tank_temperature:25,observed_input_type:'Observed API',observed_api:35,sample_temperature_unit:'F',sample_temperature:77,bsw_percent:1})
    await layout.locator('tbody input').nth(0).fill('1000');await layout.locator('tbody input').nth(1).fill('2000')
  } else {
    await fillNamed(layout,{event_time:'08:30',opening_stock_bbl:100,opening_water_bbl:10,closing_stock_bbl:150,closing_water_bbl:12})
    if(type==='FSO_OPERATIONS') await fillNamed(layout,{shuttle_number:'SH-'+key,vessel_name:'Supply Vessel',vessel_quantity_bbl:60})
  }
}

for(const theme of ['light','dark']) for(const type of Object.keys(types)) test(`${theme}: ${type} creates, reopens and submits original payload`,async({page,request},info)=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('Failed to load resource'))errors.push(m.text())})
  const api=await setup(page,request,theme)
  const c=await fixture(api,request,type)
  await page.goto('/operation-entry')
  await page.getByLabel('Operation Type',{exact:true}).selectOption(type)
  await pick(page,'Origin Location',c.loc.location_code)
  await pick(page,'Operation',c.op.operation_code)
  await pick(page,'Primary Asset',c.asset.asset_code)
  await page.locator('[name="operation_date"]').fill('2026-10-17')
  await page.locator('[name="product_name"]').fill('Crude Oil')
  if(['BARGE_OPERATIONS','SHUTTLE_OPERATIONS','TANKER_OPERATIONS'].includes(type)) await page.locator('[name="convoy_number"]').fill('VOY-'+c.key)
  await fillLayout(page,type,c.key)
  await expect(page.getByRole('button',{name:'Save Draft',exact:true})).toBeEnabled()
  await expect(page.locator('.entry-server-validation .alert-danger')).toHaveCount(0)
  const layout=page.locator('.entry-layout-container')
  if(type==='TANK_OPERATIONS') {
    await expect(layout.getByText('1,000 bbl',{exact:true})).toBeVisible()
    const titles=await layout.locator('.live-calculation-card span').allTextContents()
    expect(titles).toEqual(['TOV','Free Water','GOV','API @ 60°F','Density @ 15°C','VCF','LT Factor','Table 11 Method','Lower API @ 60°F','Upper API @ 60°F','GSV','BS&W Volume','NSV','LT','MT'])
  }
  if(type==='BARGE_OPERATIONS') {
    expect(await layout.locator('.multi-tank-grid > .multi-tank-card h4').allTextContents()).toEqual(['BEFORE','AFTER','Net Movement (After − Before)'])
  }
  await layout.screenshot({path:info.outputPath('layout-'+theme+'.png')})
  await page.getByRole('button',{name:'Save Draft',exact:true}).click()
  const dialog=page.getByRole('dialog')
  // Dialog must not close with Escape/backdrop.
  await page.keyboard.press('Escape');await expect(dialog).toBeVisible()
  const response=page.waitForResponse(r=>r.url().endsWith('/api/operation-entries')&&r.request().method()==='POST')
  await dialog.getByRole('button',{name:'Save Draft',exact:true}).click()
  const r=await response;expect(r.ok(),await r.text()).toBeTruthy();const ticket=await r.json()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.goto('/operation-entry?ticket_id='+ticket.id)
  await expect(page.getByRole('button',{name:'Update Draft',exact:true})).toBeEnabled()
  if(type==='FLOWMETER_OPERATIONS') await expect(page.locator('.entry-layout-container [name="tank_temperature"]')).toHaveValue('25')
  if(type==='BARGE_OPERATIONS') await expect(page.locator('.multi-tank-grid > .multi-tank-card').first().getByLabel('CCF',{exact:true})).toHaveValue('1.01')
  await expect(page.locator('.entry-server-validation .alert-danger')).toHaveCount(0)
  await page.getByRole('button',{name:'Review & Submit',exact:true}).click()
  const review=page.getByRole('dialog')
  await expect(review.getByRole('button',{name:'submit',exact:true})).toBeDisabled()
  await review.getByRole('checkbox').check()
  const submitted=page.waitForResponse(r=>r.url().endsWith(`/api/operation-entries/${ticket.id}/submit`))
  await review.getByRole('button',{name:'submit',exact:true}).click()
  expect((await submitted).ok()).toBeTruthy()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Update Draft',exact:true})).toHaveCount(0)
  expect(errors).toEqual([])
})

test('reference form and configuration tabs',async({page,request})=>{
  await setup(page,request,'dark')
  await page.goto('/operation-references')
  await page.getByRole('button',{name:'Add reference',exact:true}).click()
  await page.getByRole('dialog').getByLabel('Api60',{exact:true}).fill((50+Math.random()).toFixed(4))
  await page.getByRole('dialog').getByLabel('Lt Factor',{exact:true}).fill('0.12')
  await page.getByRole('dialog').getByRole('button',{name:'Save reference',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('tab',{name:'Flowmeter Config',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Flowmeter Config',exact:true})).toBeVisible()
  await page.getByRole('tab',{name:'Workflow Policies',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Workflow Policies',exact:true})).toBeVisible()
})

for (const theme of ['light','dark']) test(`${theme}: login and responsive entry shell`,async({page},info)=>{
  await page.addInitScript(theme=>{localStorage.clear();localStorage.setItem('hca.theme',theme)},theme)
  await page.goto('/operation-entry')
  await page.getByLabel('Username',{exact:true}).fill(process.env.HCA_E2E_USERNAME || 'admin')
  await page.getByLabel('Password',{exact:true}).fill(process.env.HCA_E2E_PASSWORD)
  await page.screenshot({path:info.outputPath('login.png')})
  await page.getByRole('button',{name:'Sign in to workspace',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Operation Entry',exact:true})).toBeVisible()
  await page.setViewportSize({width:1024,height:900})
  await page.screenshot({path:info.outputPath('entry-1024.png')})
  await page.setViewportSize({width:768,height:900})
  await expect(page.getByRole('heading',{name:'Operation Entry',exact:true})).toBeVisible()
  await page.screenshot({path:info.outputPath('entry-768.png')})
})

for(const [type,code,fields] of [
  ['SHUTTLE_OPERATIONS','vessel_cycle',{'Quantity (bbl)':'250','Water (bbl)':'10'}],
  ['FSO_OPERATIONS','stock_movement',{'Opening Stock':'100','Opening Water':'5','Closing Stock':'200','Closing Water':'6'}],
]) test(`fixed legacy layout: ${code}`,async({page,request})=>{
  const api=await setup(page,request,'dark'), c=await fixture(api,request,type)
  await page.goto(`/operation-entry?operation_type_code=${type}&primary_asset_code=${c.asset.asset_code}&origin_location_code=${c.loc.location_code}&operation_code=${c.op.operation_code}&convoy_number=REF-${c.key}`)
  await expect(page.getByLabel('Fixed entry layout',{exact:true})).toBeVisible()
  await page.getByLabel('Fixed entry layout',{exact:true}).selectOption(code)
  await page.locator('[name="operation_date"]').fill('2026-10-17')
  const layout=page.locator('.entry-layout-container')
  for(const [name,value] of Object.entries(fields)) await layout.getByLabel(name,{exact:true}).fill(value)
  await expect(page.getByRole('button',{name:'Save Draft',exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'Save Draft',exact:true}).click()
  const response=page.waitForResponse(r=>r.url().endsWith('/api/operation-entries')&&r.request().method()==='POST')
  await page.getByRole('dialog').getByRole('button',{name:'Save Draft',exact:true}).click()
  const r=await response;expect(r.ok(),await r.text()).toBeTruthy()
  expect((await r.json()).payload_code).toBe(code)
})

test('linked tanker receiver locks route and preserves independent measurements',async({page,request})=>{
  const api=await setup(page,request,'light'), c=await fixture(api,request,'TANKER_OPERATIONS')
  const destination=await api.post('/api/locations',{location_code:'E2E-R-'+c.key,location_name:'Receiving '+c.key,location_type:'Terminal'})
  const receiveOp=await api.post('/api/operations',{location_id:destination.id,operation_type_code:'TANKER_OPERATIONS',operation_category:'RECEIPT',operation_code:'E2E-REC-'+c.key,operation_label:'Receipt '+c.key})
  const inputs={tankerTransactionDate:'2026-10-17',tankerTransactionTime:'08:30',compartment:'C1',totalDipCm:100,waterDipCm:10,tankTemperatureUnit:'C',tankTemperature:25,
    observedInputType:'Observed API',observedApi:35,sampleTemperatureUnit:'F',sampleTemperature:77,bswPercent:1,sealC1:'S1',sealC2:'S2',sealM1:'SM1',sealM2:'SM2'}
  let t=await api.post('/api/operation-entries',{operation_type_code:'TANKER_OPERATIONS',payload_code:'tanker_payload',asset_id:c.asset.id,location_id:c.loc.id,operation_id:c.op.id,
    destination_location_id:destination.id,receiver_location_id:destination.id,convoy_number:'CONVOY-'+c.key,operation_date:'2026-10-17',payload:{inputs}})
  for(const action of ['submit','approve'])t=await api.post(`/api/operation-entries/${t.id}/${action}`,{version:t.version,review_confirmed:true})
  await page.goto('/operation-entry?linked_ticket_id='+t.id)
  await expect(page.getByText('Receiving Ticket',{exact:true})).toBeVisible()
  await expect(page.locator('input[name="convoy_number"]')).toBeDisabled()
  await expect(page.locator('input[name="convoy_number"]')).toHaveValue('CONVOY-'+c.key)
  await pick(page,'Operation',receiveOp.operation_code)
  await page.locator('input[name="operation_date"]').fill('2026-10-17')
  await fillLayout(page,'TANKER_OPERATIONS',c.key)
  await page.locator('.entry-layout-container input[name="totalDipCm"]').fill('80')
  await expect(page.getByRole('button',{name:'Save Draft',exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'Save Draft',exact:true}).click()
  const response=page.waitForResponse(r=>r.url().endsWith('/api/operation-entries')&&r.request().method()==='POST')
  await page.getByRole('dialog').getByRole('button',{name:'Save Draft',exact:true}).click()
  const r=await response;expect(r.ok(),await r.text()).toBeTruthy();const receipt=await r.json()
  expect(receipt.linked_ticket_id).toBe(t.id)
  expect(receipt.payload.inputs.totalDipCm).toBe(80)
  expect(receipt.payload.calculated.tovBbl).toBe(800)
  expect(receipt.payload.sender_reference.sender_transaction_id).toBe(t.id)
})
