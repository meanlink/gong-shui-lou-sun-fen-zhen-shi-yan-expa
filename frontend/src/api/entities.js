import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const transfers={
 list:()=>api('/transfers'),
 get:id=>api('/transfers/'+id),
 open:data=>api('/transfers',{method:'POST',body:JSON.stringify(data)}),
 segment:(id,data)=>api('/transfers/'+id+'/segments',{method:'POST',body:JSON.stringify(data)}),
 confirm:id=>api('/transfers/'+id+'/confirm',{method:'POST'}),
 publish:(id,expected_checksum)=>api('/transfers/'+id+'/publish',{method:'POST',body:JSON.stringify({expected_checksum:expected_checksum??null})}),
 revoke:id=>api('/transfers/'+id+'/revoke',{method:'POST'})
};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
