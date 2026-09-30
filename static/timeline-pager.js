'use strict';
// Each timeline owns its page, filters and stable historical snapshot.
window.TimelinePager = {
  create(fetchPage, renderPage, limit=6) {
    let page=1, totalPages=1, snapshot=null, request=0, pending=false;
    let filters={entry_type:'all',severity:''};
    async function load(next, reset=false) {
      const token=++request;
      pending=true;
      try {
      const params={limit,offset:(next-1)*limit,...filters};
      if(!reset && snapshot!==null)params.snapshot=snapshot;
      let result=await fetchPage(params);
      if(token!==request)return;
      const last=Math.max(1,Math.ceil(result.total/limit));
      if(next>last){
        next=last;
        result=await fetchPage({...params,offset:(next-1)*limit,snapshot:result.snapshot});
        if(token!==request)return;
      }
      page=next;totalPages=Math.max(1,Math.ceil(result.total/limit));snapshot=result.snapshot;
      renderPage({...result,page,totalPages});
      } finally { if(token===request)pending=false; }
    }
    return {
      go(value) {
        const number=Number(value);
        if(!Number.isSafeInteger(number)||number<1||number>totalPages)
          return Promise.reject(new Error(`请输入 1 至 ${totalPages} 之间的整数页码。`));
        return load(number);
      },
      previous:()=>load(Math.max(1,page-1)),
      next:()=>load(Math.min(totalPages,page+1)),
      latest:()=>load(1,true),
      filter(values){filters={...values};return load(1,true);},
      refresh:()=>page===1&&!pending?load(1,true):Promise.resolve(),
    };
  }
};
