/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,source:string,total_segments:number,total_rows:number,batch_checksum:string,status:string,issue:Object,received_segments:number,received_rows:number,missing_segments:number[],missing_count:number,dataset_id:?number,segments:Array<{segment_index:number,row_count:number,checksum:string,received_at:number}>}} TransferBatch */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
export {};
