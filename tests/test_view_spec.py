"""Pure browser contract/resource checks, without a server or application dataset."""
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
def test_view_spec_validation_compatibility_storage_and_conflicts():
    root = Path(__file__).parents[1] / 'src/plotsrv/static/js/core'
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const values = new Map();
global.localStorage = {getItem:key=>values.get(key)||null, setItem:(key,value)=>values.set(key,value)};
global.window = {PLOTSRV:{core:{},config:{dashboardName:'stable'}},location:{pathname:'/team/'},dispatchEvent:()=>{}};
for (const file of ['storage.js','view_spec.js']) vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+file,'utf8'));
const v = window.PLOTSRV.core.viewSpec;
const spec = {version:1,sourceId:'exact:é',name:'Mine',caption:'plain <text>',presentation:{
 search:'',filters:[{field:'value',op:'gt',value:'1',valueTo:''}],sort:[{field:'name',dir:'asc'}],group:'name',
 columns:['value','name'],hidden:[],mode:'table',plot:{type:'bar',source:'table',categoryField:'name'}},
 requirements:{fields:[{name:'value',type:'number'},{name:'name',type:'text'}],plotFields:[{name:'name',type:'text'}],plotSource:'table'}};
assert.deepEqual(v.validate(spec),spec);
for (const key of ['rows','data','credentials','path','cursor','predicate']) assert.throws(()=>v.validate({...spec,[key]:[]}));
assert.throws(()=>v.validate({...spec,version:999}));
assert.throws(()=>v.validate({...spec,caption:'x'.repeat(257)}));
const schema = {fields:{value:'number',name:'text',extra:'text'},sources:['table'],summary:{}};
assert.equal(v.compatible(spec,schema).unsafe.length,0);
const drift = v.compatible(spec,{...schema,fields:{name:'text'}});
assert.equal(drift.unsafe.length,1); assert.equal(drift.spec.presentation.filters.length,0);
assert.equal(spec.presentation.filters.length,1); // validation never mutates original
assert.equal(v.compatible(spec,{...schema,fields:{value:'text',name:'text'}}).unsafe.length,1);
const cosmetic = {...spec,presentation:{...spec.presentation,filters:[]}};
assert.equal(v.compatible(cosmetic,{...schema,fields:{value:'number'}}).unsafe.length,0);
assert(v.compatible(cosmetic,{...schema,fields:{value:'number'}}).notes.length);
const summary = JSON.parse(JSON.stringify(spec)); summary.presentation.mode='plot'; summary.presentation.plot.source='summary';
assert(v.compatible(summary,schema).unsafe.length);
const invalid = JSON.parse(JSON.stringify(spec)); invalid.presentation.filters[0].value='NaN';
assert(v.compatible(invalid,schema).unsafe.length);
v.write({id:'one',spec},false); const original = v.read().items[0];
v.write({id:'one',spec:{...spec,name:'Another tab'}},false);
assert.throws(()=>v.write(original,false,original),/another tab/);
assert.equal(v.read().items[0].spec.name,'Another tab');
const scope = v.namespace(); window.location.pathname='/other/'; assert.notEqual(scope,v.namespace());
window.location.pathname='/team'; assert.equal(scope,v.namespace());
values.set(scope,'x'.repeat(262145)); assert(v.read().error.includes('safety limit'));
values.set(scope,JSON.stringify({version:9,items:[]})); assert(v.read().error.includes('version'));
assert.throws(()=>v.write({id:'two',spec},false)); assert(values.get(scope).includes('9'));
values.set(scope,'{'); assert(v.read().error);
values.delete(scope);
for(let i=0;i<64;i++) v.write({id:String(i),spec},false);
assert.throws(()=>v.write({id:'overflow',spec},false),/full/);
const saved=v.read().items[0]; v.write(saved,true,saved); assert.equal(v.read().items.length,63);
localStorage.getItem=()=>{throw Error('disabled')}; assert(v.read().error);
'''
    subprocess.run(['node','-e',script,str(root)],check=True,capture_output=True,text=True,timeout=10)
