// Reads only: a poll never submits, retries or acknowledges a command.
export function createRemotePoller({controller,browser=window,onError=()=>{}}){
  let timer=null,generation=0,disposed=false,reading=false,failures=0;
  const eligible=s=>['requested','active'].includes(s.state)&&!!s.session;
  function schedule(){if(!disposed&&timer===null)timer=browser.setTimeout(()=>{timer=null;void tick();},1000);}
  async function tick(){
    if(disposed)return;if(reading){schedule();return;}
    const g=generation;
    try{if(!eligible(controller.snapshot()))return;
      reading=true;await controller.status();if(disposed||g!==generation)return;
      const s=controller.snapshot();
      if(eligible(s)&&!['queued','delivered','unknown'].includes(s.session.last_command_state))await controller.frame();
      failures=0;
    }catch(e){if(!disposed&&g===generation){onError(e);if(['INVALID_IMAGE','CONTRACT_MISMATCH'].includes(e.code)||++failures>=3)controller.disableControl('unavailable');}}
    finally{reading=false;if(!disposed&&g===generation&&eligible(controller.snapshot()))schedule();}
  }
  return {
    resume(){if(!disposed){failures=0;schedule();}},
    pause(){generation++;if(timer!==null)browser.clearTimeout(timer);timer=null;controller.cancelReads();},
    dispose(){this.pause();disposed=true;},
  };
}
